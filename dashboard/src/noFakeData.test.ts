// Guard: production source must not contain mock/sample market data or trading controls.
import { describe, expect, it } from "vitest";

const sources = import.meta.glob(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}", "!./**/*.d.ts"],
                                 { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const files = Object.entries(sources).map(([p, src]) => ({ p, src }));

describe("production dashboard source", () => {
  it("finds the source files", () => {
    expect(files.length).toBeGreaterThan(15);
    expect(files.some((f) => f.p.endsWith("api/client.ts"))).toBe(true);
  });

  it("contains no mock, fake, sample or random data generators", () => {
    for (const { p, src } of files) {
      expect(src, p).not.toMatch(/\b(mock|fake|dummy|lorem|faker|sampleData|seedData)\b/i);
      expect(src, p).not.toMatch(/Math\.random/);
    }
  });

  it("has no order, trade-execution or broker endpoints", () => {
    for (const { p, src } of files) {
      expect(src, p).not.toMatch(/\/api\/(orders?|trades?|execute|positions?|broker|risk)/i);
    }
  });

  it("only calls the local API through the client module", () => {
    for (const { p, src } of files) {
      if (p.endsWith("api/client.ts")) continue;
      expect(src, p).not.toMatch(/\bfetch\(/);
      expect(src, p).not.toMatch(/https?:\/\/(?!127\.0\.0\.1|localhost)/);
    }
  });
});
