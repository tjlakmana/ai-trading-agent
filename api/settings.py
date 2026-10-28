"""API settings. Loopback only: there is no option to listen on other interfaces."""

from dataclasses import dataclass, field
from pathlib import Path

from memory.scan_store import default_db_path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_PORT = 8000
# Origins allowed to send state-changing requests (the Vite dev server and the API itself).
DEFAULT_ALLOWED_ORIGIN_PORTS = (5173, 4173, 8000)


@dataclass(frozen=True)
class ApiSettings:
    db_path: Path = field(default_factory=default_db_path)
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    scan_cooldown_seconds: float = 30.0
    payload_cache_runs: int = 4
    allowed_origin_ports: tuple[int, ...] = DEFAULT_ALLOWED_ORIGIN_PORTS

    def __post_init__(self) -> None:
        if self.host not in LOOPBACK_HOSTS:
            raise ValueError(f"the dashboard API binds to loopback only, not {self.host!r}")
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port must be 1-65535")
        if not self.scan_cooldown_seconds >= 0:
            raise ValueError("scan_cooldown_seconds must be >= 0")

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(f"http://{host}:{port}" for host in ("127.0.0.1", "localhost")
                         for port in self.allowed_origin_ports)
