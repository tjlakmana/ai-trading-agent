"""Guarded manual Finviz scans for the dashboard ("Run scan now").

- One scan at a time: a request while a scan runs is refused and given the
  running job (duplicate protection).
- Cooldown: after a scan finishes, new scans wait `cooldown_seconds`.
- Runs in a background thread; clients poll the job for progress.
- Every attempt is recorded in scanner history: Finviz failures through
  run_and_record, unexpected errors best-effort as failed runs.
- Only named profiles (verified filter codes) can be scanned. Scanning never
  places orders: nothing here can reach bot/ or execution/.
"""

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from data.finviz.profiles import PROFILES, default_scan_in_play_config
from memory.recording import run_and_record
from memory.scan_store import ScanStore, redact

RUNNING, SUCCEEDED, FAILED = "RUNNING", "SUCCEEDED", "FAILED"


class UnknownProfileError(ValueError):
    pass


class ScanBusyError(Exception):
    def __init__(self, job: dict):
        super().__init__("a scan is already running")
        self.job = job


class ScanCooldownError(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"scan cooldown: retry in {retry_after:.0f}s")
        self.retry_after = retry_after


@dataclass
class ScanJob:
    job_id: str
    profile: str
    state: str
    requested_at: datetime
    finished_at: datetime | None = None
    run_id: str | None = None
    error: dict | None = None
    counts: dict | None = None


def thread_launcher(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="finviz-manual-scan", daemon=True).start()


class ScanCoordinator:
    def __init__(self, *, db_path: Path, client_factory: Callable[[], object],
                 clock: Callable[[], datetime], cooldown_seconds: float,
                 monotonic: Callable[[], float] = time.monotonic,
                 launcher: Callable[[Callable[[], None]], None] = thread_launcher,
                 keep_jobs: int = 20):
        self._db_path = Path(db_path)
        self._client_factory = client_factory
        self._clock = clock
        self._cooldown = cooldown_seconds
        self._monotonic = monotonic
        self._launch = launcher
        self._keep = keep_jobs
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, ScanJob] = OrderedDict()
        self._running: ScanJob | None = None
        self._last_finished: float | None = None

    # --- Public API ----------------------------------------------------------

    def start(self, profile: str) -> dict:
        if profile not in PROFILES:
            raise UnknownProfileError(f"unknown profile {profile!r}; choose one of {sorted(PROFILES)}")
        with self._lock:
            if self._running is not None:
                raise ScanBusyError(asdict(self._running))
            remaining = self._cooldown_remaining()
            if remaining > 0:
                raise ScanCooldownError(remaining)
            job = ScanJob(uuid.uuid4().hex, profile, RUNNING, self._clock())
            self._running = job
            self._jobs[job.job_id] = job
            while len(self._jobs) > self._keep:
                self._jobs.popitem(last=False)
        try:
            self._launch(lambda: self._run(job))
        except Exception:
            self._finish(job, FAILED, error={"type": "LaunchError", "message": "could not start the scan"})
            raise
        return self.get(job.job_id)

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return asdict(job)

    def status(self) -> dict:
        with self._lock:
            latest = next(reversed(self._jobs.values()), None)
            return {
                "running": asdict(self._running) if self._running else None,
                "latest": asdict(latest) if latest else None,
                "cooldown_seconds": self._cooldown,
                "cooldown_remaining_seconds": round(self._cooldown_remaining(), 1),
            }

    # --- Internals -----------------------------------------------------------

    def _cooldown_remaining(self) -> float:
        if self._last_finished is None:
            return 0.0
        return max(0.0, self._cooldown - (self._monotonic() - self._last_finished))

    def _run(self, job: ScanJob) -> None:
        screen, in_play = PROFILES[job.profile], default_scan_in_play_config()
        try:
            with ScanStore(self._db_path) as store:
                outcome = run_and_record(self._client_factory, screen, in_play, job.profile,
                                         store=store, clock=self._clock)
                run = store.get_run(outcome.run_id)
            counts = {"rows": run.row_count, "qualified": run.qualified_count,
                      "near_miss": run.near_miss_count, "filtered_out": run.filtered_out_count,
                      "rejected": run.rejected_count}
            if outcome.ok:
                self._finish(job, SUCCEEDED, run_id=outcome.run_id, counts=counts)
            else:
                self._finish(job, FAILED, run_id=outcome.run_id,
                             error={"type": type(outcome.error).__name__, "message": str(outcome.error)})
        except Exception as exc:  # storage failure or a bug: report it, record it if possible
            run_id = self._record_unexpected(exc, screen, in_play, job.profile)
            self._finish(job, FAILED, run_id=run_id,
                         error={"type": type(exc).__name__, "message": redact(str(exc)) or "unexpected error"})

    def _record_unexpected(self, exc, screen, in_play, profile) -> str | None:
        try:
            with ScanStore(self._db_path) as store:
                return store.record_scan_failure(exc, screen, in_play, profile, started_at=self._clock())
        except Exception:
            return None

    def _finish(self, job: ScanJob, state: str, *, run_id=None, error=None, counts=None) -> None:
        with self._lock:
            job.state, job.run_id, job.error, job.counts = state, run_id, error, counts
            job.finished_at = self._clock()
            if self._running is job:
                self._running = None
            self._last_finished = self._monotonic()
