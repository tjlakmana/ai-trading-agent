import { describe, expect, it } from "vitest";

import { DASH, ageSeconds, fmtAge, fmtCheckValue, fmtEt, fmtInt, fmtPct, fmtPrice, fmtRatio, fmtShares } from "./format";

describe("number formatting", () => {
  it("never renders missing values as zero", () => {
    for (const f of [fmtPct, fmtPrice, fmtRatio, fmtInt, fmtShares]) {
      expect(f(null)).toBe(DASH);
      expect(f(undefined)).toBe(DASH);
    }
  });
  it("formats fractions as signed percentages", () => {
    expect(fmtPct(0.3)).toBe("+30.0%");
    expect(fmtPct(-0.0101, 2)).toBe("-1.01%");
    expect(fmtPct(0)).toBe("0.0%");
    expect(fmtPct(0.044, 1, false)).toBe("4.4%");
  });
  it("formats prices, ratios and share counts", () => {
    expect(fmtPrice(6.5)).toBe("$6.50");
    expect(fmtPrice(0.5123)).toBe("$0.5123");
    expect(fmtRatio(8)).toBe("8.00×");
    expect(fmtShares(6_000_000)).toBe("6.00M");
    expect(fmtShares(2_001_440_000)).toBe("2.00B");
    expect(fmtShares(950_000)).toBe("950.0K");
    expect(fmtShares(512)).toBe("512");
    expect(fmtInt(4_000_000)).toBe("4,000,000");
  });
});

describe("time formatting", () => {
  it("shows US Eastern time with the zone, from UTC", () => {
    expect(fmtEt("2026-10-28T18:57:39Z")).toBe("2026-10-28 14:57:39 EDT");
    expect(fmtEt("2026-12-02T14:30:00Z", false)).toBe("09:30:00 EST");
    expect(fmtEt(null)).toBe(DASH);
    expect(fmtEt("not a date")).toBe(DASH);
  });
  it("formats ages compactly", () => {
    expect(fmtAge(45)).toBe("45s");
    expect(fmtAge(125)).toBe("2m");
    expect(fmtAge(3 * 3600 + 5 * 60)).toBe("3h 05m");
    expect(fmtAge(3 * 86400)).toBe("3d");
    expect(fmtAge(null)).toBe(DASH);
  });
  it("computes fetch age from fetched_at", () => {
    expect(ageSeconds("2026-10-28T18:00:00Z", Date.parse("2026-10-28T18:01:30Z"))).toBe(90);
    expect(ageSeconds(null, Date.now())).toBeNull();
  });
});

describe("check values", () => {
  it("uses the unit implied by the check", () => {
    expect(fmtCheckValue("min_pct_change", 0.1)).toBe("+10.0%");
    expect(fmtCheckValue("max_price", 20)).toBe("$20.00");
    expect(fmtCheckValue("min_volume_vs_avg_daily", 3)).toBe("3.00×");
    expect(fmtCheckValue("min_cumulative_volume", 500_000)).toBe("500,000");
    expect(fmtCheckValue("max_float_shares", 20_000_000)).toBe("20,000,000");
    expect(fmtCheckValue("catalyst", "present")).toBe("present");
    expect(fmtCheckValue("room_to_resistance", 0.2)).toBe("+20.0%");
    expect(fmtCheckValue("catalyst", null)).toBe(DASH);
  });
});
