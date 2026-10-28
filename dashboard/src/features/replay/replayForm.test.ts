import { describe, expect, it } from "vitest";

import type { ConfigField } from "../../api/types";
import { buildOverrides, initialInputs, parseField } from "./replayForm";

// Field metadata in the shape returned by GET /api/in-play-config.
const F = {
  pct: { name: "min_pct_change", kind: "float", nullable: true, unit: "fraction", default: 0.1, scan_default: 0.1, description: "" },
  float: { name: "max_float_shares", kind: "int", nullable: true, unit: "shares", default: 20000000, scan_default: 20000000, description: "" },
  room: { name: "min_room_to_resistance_pct", kind: "float", nullable: false, unit: "fraction", default: 0.2, scan_default: 0.2, description: "" },
  level: { name: "catalyst_level", kind: "level", nullable: false, unit: "level", default: "PREFERRED", scan_default: "PREFERRED", description: "" },
} satisfies Record<string, ConfigField>;
const fields = Object.values(F);
const stored = { min_pct_change: 0.1, max_float_shares: 20000000, min_room_to_resistance_pct: 0.2, catalyst_level: "PREFERRED" };

describe("parseField", () => {
  it("parses numbers, whole share counts and levels", () => {
    expect(parseField(F.pct, { text: "0.2", off: false })).toEqual({ ok: true, value: 0.2 });
    expect(parseField(F.float, { text: "10,000,000", off: false })).toEqual({ ok: true, value: 10_000_000 });
    expect(parseField(F.level, { text: "hard", off: false })).toEqual({ ok: true, value: "HARD" });
  });
  it("rejects bad input instead of guessing", () => {
    expect(parseField(F.pct, { text: "abc", off: false }).ok).toBe(false);
    expect(parseField(F.pct, { text: "", off: false }).ok).toBe(false);
    expect(parseField(F.float, { text: "1.5", off: false }).ok).toBe(false);
    expect(parseField(F.float, { text: "-5", off: false }).ok).toBe(false);
    expect(parseField(F.level, { text: "SOMETIMES", off: false }).ok).toBe(false);
  });
  it("turns a threshold off only when it is nullable", () => {
    expect(parseField(F.float, { text: "", off: true })).toEqual({ ok: true, value: null });
    expect(parseField(F.room, { text: "", off: true }).ok).toBe(false);
  });
});

describe("buildOverrides", () => {
  it("sends nothing when nothing changed", () => {
    expect(buildOverrides(fields, stored, initialInputs(fields, stored))).toEqual({ overrides: {}, errors: [] });
  });
  it("sends only changed fields", () => {
    const inputs = { ...initialInputs(fields, stored), min_pct_change: { text: "0.02", off: false },
                     max_float_shares: { text: "", off: true } };
    expect(buildOverrides(fields, stored, inputs)).toEqual({
      overrides: { min_pct_change: 0.02, max_float_shares: null }, errors: [] });
  });
  it("collects errors", () => {
    const inputs = { ...initialInputs(fields, stored), max_float_shares: { text: "lots", off: false } };
    const { overrides, errors } = buildOverrides(fields, stored, inputs);
    expect(overrides).toEqual({});
    expect(errors).toHaveLength(1);
  });
  it("starts disabled thresholds as off", () => {
    const inputs = initialInputs(fields, { ...stored, max_float_shares: null });
    expect(inputs.max_float_shares).toEqual({ text: "", off: true });
  });
});
