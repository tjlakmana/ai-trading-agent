import { useState } from "react";
import { Link } from "react-router";

import { useProfiles } from "../../api/queries";
import { useNow } from "../../lib/useNow";
import { buttonModel } from "./scanState";
import { useScan } from "./useScan";

/** Top-bar "Run scan now": one guarded manual Finviz scan (research only; never places orders). */
export function ScanControl() {
  const profiles = useProfiles();
  const [profile, setProfile] = useState<string>("broad_v1");
  const { state, status, start, dismiss } = useScan();
  const now = useNow(500);
  const model = buttonModel(state, status, now);
  const runId = state.phase === "succeeded" || state.phase === "failed" ? state.job?.run_id : undefined;

  return (
    <div className="scan-control">
      <select aria-label="Scan profile" value={profile} onChange={(e) => setProfile(e.target.value)}
              disabled={model.tone === "busy" || !profiles.data}
              title={profiles.data?.find((p) => p.name === profile)?.filters.map((f) => f.meaning).join(", ")}>
        {(profiles.data ?? []).map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
      </select>
      <button className={`btn btn-scan tone-${model.tone}`} disabled={model.disabled}
              onClick={() => void start(profile)} aria-live="polite">
        {model.tone === "busy" && <span className="spinner" aria-hidden />}
        {model.label}
      </button>
      {model.message && (
        <span className={`scan-msg tone-${model.tone}`} role={model.tone === "error" ? "alert" : "status"}>
          {model.message}
          {runId && <> · <Link to={`/runs/${runId}`}>view run</Link></>}
          {(state.phase === "failed" || state.phase === "succeeded") && (
            <button className="link-btn" onClick={dismiss} aria-label="Dismiss">✕</button>
          )}
        </span>
      )}
    </div>
  );
}
