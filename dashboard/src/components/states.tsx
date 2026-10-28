import type { ReactNode } from "react";

import { ApiError } from "../api/client";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="state state-loading" role="status">{label}</div>;
}

export function ErrorBox({ error, title = "Could not load data" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  const offline = error instanceof TypeError || (error instanceof ApiError && error.status >= 502);
  return (
    <div className="state state-error" role="alert">
      <strong>{title}</strong>
      <span>{message}</span>
      {offline && <span className="muted small">Is the backend running? Start it with: python -m api</span>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}
