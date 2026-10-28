import { useCallback, useState } from "react";

// Per-viewer UI convenience only (which panels are collapsed). Never holds data.
// Storage can be missing or throw (private windows, blocked site data): fall back to defaults.
const KEY = "momentum-desk:collapsed:v1";

export interface CollapseStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function defaultStore(): CollapseStore | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function readCollapsed(store: CollapseStore | null): Record<string, boolean> {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([, v]) => typeof v === "boolean")) as Record<string, boolean>;
  } catch {
    return {};
  }
}

export function writeCollapsed(store: CollapseStore | null, id: string, collapsed: boolean): void {
  try {
    store?.setItem(KEY, JSON.stringify({ ...readCollapsed(store), [id]: collapsed }));
  } catch {
    /* storage unavailable: keep the in-memory state only */
  }
}

/** Collapsed state for one panel, remembered per browser when storage is available. */
export function useCollapsed(id: string, initial: boolean): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(defaultStore())[id] ?? initial);
  const toggle = useCallback(() => {
    setCollapsed((c) => {
      writeCollapsed(defaultStore(), id, !c);
      return !c;
    });
  }, [id]);
  return [collapsed, toggle];
}
