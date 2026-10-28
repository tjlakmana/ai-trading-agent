import { useEffect, useRef } from "react";

import { RowDetail } from "./RowDetail";

/**
 * Non-modal side panel with the selected stock's full explanation. The scanner stays
 * usable behind it: clicking another row updates the panel. Escape or ✕ closes it.
 */
export function StockDrawer({ runId, rowNumber, onClose }: {
  runId: string | undefined; rowNumber: number | undefined; onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const open = runId !== undefined && rowNumber !== undefined;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => { if (open) closeRef.current?.focus({ preventScroll: true }); }, [open, runId, rowNumber]);

  if (!open) return null;
  return (
    <aside className="drawer" aria-label="Selected stock details">
      <div className="drawer-head">
        <h2>Why it passed or failed</h2>
        <button ref={closeRef} className="btn btn-ghost" onClick={onClose} aria-label="Close stock details">✕</button>
      </div>
      <div className="drawer-body">
        <RowDetail runId={runId} rowNumber={rowNumber} />
      </div>
    </aside>
  );
}
