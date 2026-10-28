import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../api/client";
import { useConfigFields } from "../../api/queries";
import type { ConfigField, Run } from "../../api/types";
import { ClassBadge } from "../../components/badges";
import { Panel } from "../../components/Panel";
import { ErrorBox, Loading } from "../../components/states";
import { humanize } from "../../lib/format";
import { buildOverrides, initialInputs, type FieldInput } from "./replayForm";

const UNIT_HINT: Record<string, string> = {
  fraction: "fraction (0.10 = 10%)", dollars: "dollars", ratio: "ratio (×)", shares: "shares", level: "",
};

/** Deterministic replay of a recorded run's stored snapshots with different in-play settings. Never saved. */
export function ReplayPanel({ run }: { run: Run }) {
  const fields = useConfigFields();
  if (run.status !== "OK") return null;
  return (
    <Panel title="Deterministic replay" badge={<span className="badge mod-available">Read-only</span>}>
      <p className="hint">
        Re-runs the in-play filter on this run&apos;s stored snapshots. Results are computed on demand and never written
        to history. Changing settings here does not change the strategy or any risk rule.
      </p>
      {fields.isPending ? <Loading /> : fields.isError ? <ErrorBox error={fields.error} /> :
        <ReplayForm run={run} fields={fields.data} />}
    </Panel>
  );
}

function ReplayForm({ run, fields }: { run: Run; fields: ConfigField[] }) {
  const stored = run.in_play_config as Record<string, unknown>;
  const initial = useMemo(() => initialInputs(fields, stored), [fields, stored]);
  const [inputs, setInputs] = useState<Record<string, FieldInput>>(initial);
  const { overrides, errors } = buildOverrides(fields, stored, inputs);
  const replay = useMutation({ mutationFn: () => api.replay(run.run_id, overrides) });
  const set = (name: string, patch: Partial<FieldInput>) =>
    setInputs((prev) => ({ ...prev, [name]: { ...prev[name]!, ...patch } }));

  return (
    <div className="replay">
      <form className="replay-form" onSubmit={(e) => { e.preventDefault(); if (!errors.length) replay.mutate(); }}>
        {fields.map((f) => {
          const input = inputs[f.name]!;
          const changed = f.name in overrides;
          return (
            <label key={f.name} className={`field ${changed ? "changed" : ""}`} title={f.description}>
              <span className="field-name">{humanize(f.name)}</span>
              <span className="field-row">
                {f.kind === "level" ? (
                  <select value={input.text.toUpperCase()} onChange={(e) => set(f.name, { text: e.target.value })}>
                    {["HARD", "PREFERRED", "OFF"].map((l) => <option key={l}>{l}</option>)}
                  </select>
                ) : (
                  <input inputMode="decimal" value={input.text} disabled={input.off}
                         onChange={(e) => set(f.name, { text: e.target.value })} />
                )}
                {f.nullable && (
                  <span className="off-toggle">
                    <input type="checkbox" checked={input.off} onChange={(e) => set(f.name, { off: e.target.checked })} /> off
                  </span>
                )}
              </span>
              <span className="muted small">{UNIT_HINT[f.unit] ?? f.unit}</span>
            </label>
          );
        })}
        <div className="replay-actions">
          <button className="btn btn-primary" type="submit" disabled={errors.length > 0 || replay.isPending}>
            {replay.isPending ? "Replaying…" : `Replay${Object.keys(overrides).length ? ` (${Object.keys(overrides).length} change${Object.keys(overrides).length > 1 ? "s" : ""})` : " original settings"}`}
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => { setInputs(initial); replay.reset(); }}>Reset</button>
          {errors.length > 0 && <span className="tone-error small">{errors.join(" · ")}</span>}
        </div>
      </form>
      {replay.isError && <ErrorBox error={replay.error} title="Replay rejected" />}
      {replay.data && (
        <div className="replay-result">
          <div className="counts-compare">
            {(["qualified", "near_miss", "filtered_out", "rejected"] as const).map((k) => (
              <div key={k} className="count-cell">
                <span className="muted small">{humanize(k)}</span>
                <span className="big">{replay.data.counts[k]}</span>
                <span className="muted small">was {replay.data.original_counts[k]}</span>
              </div>
            ))}
          </div>
          <p className="muted small">{replay.data.note}</p>
          {replay.data.changed.length === 0 ? <p>No stock changed class.</p> : (
            <table className="data-table compact">
              <thead><tr><th>Ticker</th><th>Recorded</th><th>Replayed</th><th>HARD checks not passing</th></tr></thead>
              <tbody>
                {replay.data.changed.map((c) => (
                  <tr key={c.row_number}>
                    <td className="ticker"><span className="sym">{c.ticker}</span></td>
                    <td><ClassBadge status={c.original_status} /></td>
                    <td><ClassBadge status={c.status} /></td>
                    <td className="why">{c.reasons.join("; ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
