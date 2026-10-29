import type { BoardEntry } from './types';

// Stubs (DEC-010): the red commit holds these so the tests fail on an assertion.
type Instant = string | Date;

export function durationText(minutes: number): string {
  void minutes;
  return '';
}

export function dataAgeText(reportedAt: Instant, now: Instant): string {
  void reportedAt;
  void now;
  return '';
}

export function londonTime(instant: Instant): string {
  void instant;
  return '';
}

export function londonDate(instant: Instant): string {
  void instant;
  return '';
}

export function nextDueText(nextDueAt: Instant, now: Instant): string {
  void nextDueAt;
  void now;
  return '';
}

export function ageLineText(entry: BoardEntry, now: Instant): string {
  void entry;
  void now;
  return '';
}

export function categoryLabel(category: string): string {
  void category;
  return '';
}
