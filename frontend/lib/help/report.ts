// The Help screens' reports (W46): the safety concern and the problem report, checked as the back end
// checks them (domain/rules/safety_report.py, U41). A refusal is a plain sentence the screen can show.
// Pure, except `supportSharingOn`, which reads the one flag the build sets.

export const SAFETY_CATEGORIES = [
  'wrong-service-shown',
  'out-of-date-criteria',
  'wrong-status-on-board',
  'message-went-to-wrong-place',
  'something-else',
] as const;
export const PROBLEM_KINDS = ['screen-slow', 'button-does-not-work', 'figure-looks-wrong', 'something-else'] as const;
export const REPORT_LIMIT = 280;

export type SafetyCategory = (typeof SAFETY_CATEGORIES)[number];
export type ProblemKind = (typeof PROBLEM_KINDS)[number];
export type Checked<T> = { ok: true; value: T } | { ok: false; errors: string[] };

export type SafetyConcern = { category: SafetyCategory; text: string; reference?: string };
export type Problem = { kind: ProblemKind; route: string; text?: string };

const REFERENCE = /^[A-Za-z0-9-]{1,40}$/;
const PAGE_PATH = /^\/[A-Za-z0-9\-_./[\]]{0,200}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function checkSafetyConcern(input: unknown): Checked<SafetyConcern> {
  const source = isRecord(input) ? input : {};
  const errors: string[] = [];
  const category = source.category;
  if (typeof category !== 'string' || !(SAFETY_CATEGORIES as readonly string[]).includes(category)) {
    errors.push('Choose what it is about.');
  }
  const text = typeof source.text === 'string' ? source.text.trim() : '';
  if (text === '') errors.push('Tell us what happened.');
  if (text.length > REPORT_LIMIT) errors.push(`Keep it to ${REPORT_LIMIT} characters`);
  const reference = typeof source.reference === 'string' ? source.reference.trim() : '';
  if (reference !== '' && !REFERENCE.test(reference)) errors.push('Check the reference.');
  if (errors.length > 0) return { ok: false, errors };
  const value: SafetyConcern = { category: category as SafetyCategory, text };
  if (reference !== '') value.reference = reference;
  return { ok: true, value };
}

export function checkProblem(input: unknown): Checked<Problem> {
  const source = isRecord(input) ? input : {};
  const errors: string[] = [];
  const kind = source.kind;
  if (typeof kind !== 'string' || !(PROBLEM_KINDS as readonly string[]).includes(kind)) errors.push('Choose one.');
  const route = typeof source.route === 'string' ? source.route : '';
  if (!PAGE_PATH.test(route) || route.startsWith('//')) errors.push('Check the page.');
  const text = typeof source.text === 'string' ? source.text.trim() : '';
  if (text.length > REPORT_LIMIT) errors.push(`Keep it to ${REPORT_LIMIT} characters`);
  if (errors.length > 0) return { ok: false, errors };
  const value: Problem = { kind: kind as ProblemKind, route };
  if (text !== '') value.text = text;
  return { ok: true, value };
}

/** The page the person came from, if it is a page path; otherwise the help page. */
export function pagePath(value: string | undefined): string {
  return value !== undefined && PAGE_PATH.test(value) && !value.startsWith('//') ? value : '/help';
}

/** The support-sharing flag: on only when the build says exactly "on" (W46, removed by W56). */
export function supportSharingOn(): boolean {
  return process.env.NEXT_PUBLIC_SUPPORT_SHARING === 'on';
}
