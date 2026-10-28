import { describe, expect, it } from "vitest";

import { readCollapsed, writeCollapsed, type CollapseStore } from "./collapse";

function memoryStore(initial: Record<string, string> = {}): CollapseStore & { data: Record<string, string> } {
  const data = { ...initial };
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; } };
}

const KEY = "momentum-desk:collapsed:v1";

describe("collapse persistence", () => {
  it("round-trips per-panel state", () => {
    const store = memoryStore();
    writeCollapsed(store, "paper", false);
    writeCollapsed(store, "level2", true);
    expect(readCollapsed(store)).toEqual({ paper: false, level2: true });
  });
  it("ignores corrupt or unexpected stored values", () => {
    expect(readCollapsed(memoryStore({ [KEY]: "not json" }))).toEqual({});
    expect(readCollapsed(memoryStore({ [KEY]: "[true]" }))).toEqual({});
    expect(readCollapsed(memoryStore({ [KEY]: '{"a":true,"b":"yes"}' }))).toEqual({ a: true });
  });
  it("works without storage and when storage throws", () => {
    expect(readCollapsed(null)).toEqual({});
    const throwing: CollapseStore = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(readCollapsed(throwing)).toEqual({});
    expect(() => writeCollapsed(throwing, "x", true)).not.toThrow();
  });
});
