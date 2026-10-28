// Pure helpers for the replay form (unit tested). Only fields the user actually changed
// are sent; the backend validates again and rejects anything invalid.
import type { ConfigField, OverrideValue } from "../../api/types";

export interface FieldInput {
  text: string;
  off: boolean; // true = threshold disabled (null)
}

export type Parsed = { ok: true; value: OverrideValue } | { ok: false; error: string };

const LEVELS = ["HARD", "PREFERRED", "OFF"];

export function initialInputs(fields: ConfigField[], stored: Record<string, unknown>): Record<string, FieldInput> {
  return Object.fromEntries(fields.map((f) => {
    const v = stored[f.name];
    return [f.name, { text: v == null ? "" : String(v), off: v == null && f.nullable }];
  }));
}

export function parseField(field: ConfigField, input: FieldInput): Parsed {
  if (input.off) {
    return field.nullable ? { ok: true, value: null } : { ok: false, error: `${field.name} cannot be turned off` };
  }
  const text = input.text.trim();
  if (field.kind === "level") {
    const level = text.toUpperCase();
    return LEVELS.includes(level) ? { ok: true, value: level } : { ok: false, error: `${field.name}: choose ${LEVELS.join(", ")}` };
  }
  if (field.kind === "int") {
    const digits = text.replace(/[,_\s]/g, "");
    if (!/^\d+$/.test(digits)) return { ok: false, error: `${field.name}: whole number of shares` };
    return { ok: true, value: Number(digits) };
  }
  if (text === "" || !Number.isFinite(Number(text))) return { ok: false, error: `${field.name}: enter a number` };
  return { ok: true, value: Number(text) };
}

export function buildOverrides(fields: ConfigField[], stored: Record<string, unknown>,
                               inputs: Record<string, FieldInput>) {
  const overrides: Record<string, OverrideValue> = {};
  const errors: string[] = [];
  for (const f of fields) {
    const input = inputs[f.name];
    if (!input) continue;
    const parsed = parseField(f, input);
    if (!parsed.ok) {
      errors.push(parsed.error);
      continue;
    }
    const original = stored[f.name] ?? null;
    if (parsed.value !== original) overrides[f.name] = parsed.value;
  }
  return { overrides, errors };
}
