import { FhirError } from '@/lib/fhir/client';

// The week of the network summary: Monday to Sunday, the back end's `weekStart` a Monday (400 otherwise).
// Pure; no clock except the one `lastCompleteWeekStart` is given.

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

/** True for a real calendar date written `YYYY-MM-DD` that is a Monday. */
export function isMonday(day: string): boolean {
  if (!DAY.test(day)) return false;
  const at = new Date(`${day}T00:00:00Z`);
  return !Number.isNaN(at.getTime()) && at.toISOString().slice(0, 10) === day && at.getUTCDay() === 1;
}

/** The Monday that starts the last complete Monday-to-Sunday week before `now` (UTC date). */
export function lastCompleteWeekStart(now: Date): string {
  const today = new Date(`${now.toISOString().slice(0, 10)}T00:00:00Z`).getTime();
  const sinceMonday = (now.getUTCDay() + 6) % 7;
  return new Date(today - (sinceMonday + 7) * DAY_MS).toISOString().slice(0, 10);
}

/** `?weekStart=<Monday>` from a request, or a 400. */
export function weekStartQuery(request: Request): string {
  const value = new URL(request.url).searchParams.get('weekStart');
  if (value === null || !isMonday(value)) {
    throw new FhirError(400, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'The request was not valid.' }] });
  }
  return `?weekStart=${value}`;
}
