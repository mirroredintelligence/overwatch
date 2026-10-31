import type { SettingJson, SettingSpec } from './views';
import { humaniseKey } from './words';

// The rules of the settings draft form, as pure functions (TEN-076): what a field holds, what it is
// checked against, and what is sent. The back end checks every value again against the registry; these
// say the same things first, in words, next to the field. A value is only checked when it was changed: a
// setting the person did not touch is not sent and not blamed.

/** What the form holds for one setting: text for a number, a time or a text, a flag, or a set of codes. */
export type FieldValue = string | boolean | string[];

export function effective(spec: SettingSpec, values: Readonly<Record<string, SettingJson>>): SettingJson | null {
  return spec.key in values ? (values[spec.key] ?? null) : spec.default;
}

export function toField(spec: SettingSpec, value: SettingJson | null): FieldValue {
  if (spec.kind === 'codes') return Array.isArray(value) ? [...value] : [];
  if (spec.kind === 'bool') return value === true;
  return value === null || value === undefined ? '' : String(value);
}

function sameField(a: FieldValue, b: FieldValue): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && [...a].sort().join('\n') === [...b].sort().join('\n');
  return a === b;
}

export function isChanged(spec: SettingSpec, now: FieldValue, field: FieldValue): boolean {
  return !sameField(now, field);
}

function inClock(value: string, min: string | number | null, max: string | number | null): boolean {
  if (!/^\d{2}:\d{2}$/.test(value)) return false;
  const hours = Number(value.slice(0, 2));
  const minutes = Number(value.slice(3));
  if (hours > 23 || minutes > 59) return false;
  if (typeof min === 'string' && value < min) return false;
  if (typeof max === 'string' && value > max) return false;
  return true;
}

/** The words for a value that is not allowed, or null when it is. */
export function problemWith(spec: SettingSpec, field: FieldValue): string | null {
  const min = spec.minimum;
  const max = spec.maximum;
  switch (spec.kind) {
    case 'int': {
      if (typeof field !== 'string' || !/^\d{1,9}$/.test(field)) return rangeWords(spec);
      const n = Number(field);
      if (spec.choices !== null) return spec.choices.includes(n) ? null : `Choose ${spec.choices.join(' or ')}.`;
      if ((typeof min === 'number' && n < min) || (typeof max === 'number' && n > max)) return rangeWords(spec);
      return null;
    }
    case 'time':
      return typeof field === 'string' && inClock(field, min, max) ? null : `Enter a time as HH:MM, from ${String(min)} to ${String(max)}.`;
    case 'text': {
      const length = typeof field === 'string' ? field.trim().length : 0;
      const lo = typeof min === 'number' ? min : 1;
      const hi = typeof max === 'number' ? max : 200;
      return length >= lo && length <= hi ? null : `Enter ${lo} to ${hi} characters.`;
    }
    case 'codes':
      return Array.isArray(field) && field.every((c) => spec.allowed === null || spec.allowed.includes(c)) ? null : 'Choose from the codes shown.';
    case 'bool':
      return null;
  }
}

function rangeWords(spec: SettingSpec): string {
  const { minimum: min, maximum: max } = spec;
  if (typeof min === 'number' && typeof max === 'number') return `Enter a whole number from ${min} to ${max}.`;
  return 'Enter a whole number.';
}

/** The value as the back end takes it. */
export function toWire(spec: SettingSpec, field: FieldValue): SettingJson {
  if (spec.kind === 'int') return Number(field);
  if (spec.kind === 'codes') return [...(field as string[])].sort();
  if (spec.kind === 'text') return (field as string).trim();
  return field as SettingJson;
}

/** What a setting is now, in a line a person can check the field against. */
export function hintFor(spec: SettingSpec, values: Readonly<Record<string, SettingJson>>): string {
  const unit = spec.kind === 'int' && spec.unit !== 'count' ? ` ${spec.unit}` : '';
  const say = (v: SettingJson | null) => (v === null ? 'not set' : Array.isArray(v) ? v.join(', ') : `${String(v)}${typeof v === 'number' ? unit : ''}`);
  const parts = [`Now ${say(effective(spec, values))}.`];
  if (spec.default !== null) parts.push(`Default ${say(spec.default)}.`);
  if (spec.kind === 'int' && spec.choices !== null) parts.push(`Choose ${spec.choices.join(' or ')}.`);
  else if (spec.kind === 'int' && spec.minimum !== null) parts.push(`From ${spec.minimum} to ${spec.maximum}${unit}.`);
  else if (spec.kind === 'time') parts.push(`From ${String(spec.minimum)} to ${String(spec.maximum)}.`);
  else if (spec.kind === 'text') parts.push(`From ${String(spec.minimum)} to ${String(spec.maximum)} characters.`);
  return parts.join(' ');
}

export type Draft = { changes: Record<string, SettingJson>; removals: string[]; problems: { key: string; message: string }[] };

/** The change the form makes, against the values in force. */
export function buildDraft(
  specs: readonly SettingSpec[],
  values: Readonly<Record<string, SettingJson>>,
  fields: Readonly<Record<string, FieldValue>>,
  useDefault: ReadonlySet<string>,
): Draft {
  const draft: Draft = { changes: {}, removals: [], problems: [] };
  for (const spec of specs) {
    if (useDefault.has(spec.key)) {
      draft.removals.push(spec.key);
      continue;
    }
    const field = fields[spec.key];
    if (field === undefined) continue;
    const now = toField(spec, effective(spec, values));
    if (!isChanged(spec, now, field)) continue;
    const problem = problemWith(spec, field);
    if (problem !== null) draft.problems.push({ key: spec.key, message: problem });
    else draft.changes[spec.key] = toWire(spec, field);
  }
  return draft;
}

export function fieldId(key: string): string {
  return `setting-${key}`;
}

export function labelFor(key: string): string {
  return humaniseKey(key);
}
