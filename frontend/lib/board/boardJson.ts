import { BoardParseError, isStatus } from './parse';
import type { Board, BoardEntry } from './types';

// Reads the board the BFF sends the browser (the JSON of a Board) and fails
// closed. The browser trusts the BFF no more than the BFF trusts the back end: a
// status it does not know, a missing or mistyped field, or a count that is not a
// whole number of at least zero is an error, never a guess. The caller then shows
// Last known, so the wall never shows a blank or a wrong tile. It builds a new
// object from the fields it knows, so nothing unexpected reaches the screen.

function fail(what: string): never {
  // Names the field only. Never a value from the body.
  throw new BoardParseError(`The board is not in the expected shape (${what}).`);
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(`${what} is not an object`);
  return value as Record<string, unknown>;
}

function text(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== 'string') fail(`${key} is missing or not text`);
  return value;
}

function nullableText(source: Record<string, unknown>, key: string): string | null {
  const value = source[key];
  if (value === null) return null;
  return text(source, key);
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function count(source: Record<string, unknown>, key: string): number {
  const value = source[key];
  if (!isCount(value)) fail(`${key} is missing or not a count`);
  return value;
}

function nullableCount(source: Record<string, unknown>, key: string): number | null {
  return source[key] === null ? null : count(source, key);
}

function isInstant(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

function instant(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (!isInstant(value)) fail(`${key} is missing or not a time`);
  return value;
}

function nullableInstant(source: Record<string, unknown>, key: string): string | null {
  return source[key] === null ? null : instant(source, key);
}

function entryFrom(value: unknown): BoardEntry {
  const source = record(value, 'an entry');
  const status = text(source, 'status');
  if (!isStatus(status)) fail('status is not one the board knows');
  return {
    serviceId: text(source, 'serviceId'),
    name: text(source, 'name'),
    category: text(source, 'category'),
    status,
    effectiveAvailable: nullableCount(source, 'effectiveAvailable'),
    overBy: nullableCount(source, 'overBy'),
    used: nullableCount(source, 'used'),
    established: count(source, 'established'),
    pending: count(source, 'pending'),
    unitLabel: text(source, 'unitLabel'),
    comment: nullableText(source, 'comment'),
    reportedAt: nullableInstant(source, 'reportedAt'),
    nextDueAt: nullableInstant(source, 'nextDueAt'),
    wasDueAt: nullableInstant(source, 'wasDueAt'),
  };
}

export function parseBoardJson(value: unknown): Board {
  const source = record(value, 'the board');
  const entries = source.entries;
  if (!Array.isArray(entries)) fail('entries is missing or not a list');
  const allLimitedOrWorse = source.allLimitedOrWorse;
  if (typeof allLimitedOrWorse !== 'boolean') fail('allLimitedOrWorse is missing or not true or false');
  return {
    entries: entries.map(entryFrom),
    pressure: text(source, 'pressure'),
    allLimitedOrWorse,
    generatedAt: instant(source, 'generatedAt'),
    organisation: nullableText(source, 'organisation'),
  };
}
