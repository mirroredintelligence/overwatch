import { excludeLabel, NEED_LABELS } from './model';
import type { CriteriaValues, NeedCode } from './types';

// What changed between two versions, in the words the owner and the approver read (W30, W31). Pure.
// Each list says what was removed, then what was added, and the fields are in a fixed order, so the
// same change always reads the same.

const limitText = (age: number | null): string => (age === null ? 'No limit' : String(age));

function listChanges(
  prefix: string,
  before: readonly string[],
  after: readonly string[],
  label: (value: string) => string,
): string[] {
  const kept = new Set(after);
  const had = new Set(before);
  const removed = before.filter((value) => !kept.has(value)).map(label);
  const added = after.filter((value) => !had.has(value)).map(label);
  const lines: string[] = [];
  if (removed.length > 0) lines.push(`${prefix}: removed ${removed.join(', ')}`);
  if (added.length > 0) lines.push(`${prefix}: added ${added.join(', ')}`);
  return lines;
}

export function diffCriteria(before: CriteriaValues, after: CriteriaValues): string[] {
  const lines: string[] = [];
  if (before.ageMin !== after.ageMin) lines.push(`Youngest age ${before.ageMin} to ${after.ageMin}`);
  if (before.ageMax !== after.ageMax) lines.push(`Oldest age ${limitText(before.ageMax)} to ${limitText(after.ageMax)}`);
  lines.push(...listChanges('Accepts', before.accepts, after.accepts, (need) => NEED_LABELS[need as NeedCode]));
  lines.push(...listChanges('Does not accept', before.excludes, after.excludes, (need) => excludeLabel(need as NeedCode)));
  lines.push(...listChanges('Postcode districts', before.districts, after.districts, (district) => district));
  return lines;
}
