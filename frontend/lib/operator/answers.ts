import { FhirError } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';

// What the operator and tenant-administrator BFF routes need to read an answer of the back end (W9C): a
// shape that is not the one expected is an error (a fixed 502), never an empty list or a half page. Every
// reader here picks the fields a screen shows and drops the rest, so a field the back end adds later (or one
// that should never have come, such as a secret reference) cannot reach the browser by accident.

const BAD_ANSWER: OperationOutcome = {
  resourceType: 'OperationOutcome',
  issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end answered something that is not what was expected.' }],
};

/** The error a reader throws: a 502 the BFF answers with its fixed words. */
export function badAnswer(): FhirError {
  return new FhirError(502, BAD_ANSWER);
}

export type Obj = Record<string, unknown>;

export function obj(value: unknown): Obj {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw badAnswer();
  return value as Obj;
}

export function list(value: unknown, max = 5000): unknown[] {
  if (!Array.isArray(value) || value.length > max) throw badAnswer();
  return value;
}

export function str(value: unknown, max = 1000): string {
  if (typeof value !== 'string' || value.length > max) throw badAnswer();
  return value;
}

export function strOrNull(value: unknown, max = 1000): string | null {
  if (value === null || value === undefined) return null;
  return str(value, max);
}

export function num(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw badAnswer();
  return value;
}

export function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return num(value);
}

export function bool(value: unknown): boolean {
  if (typeof value !== 'boolean') throw badAnswer();
  return value;
}

export function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) throw badAnswer();
  return value as T;
}

export function strings(value: unknown, max = 500): string[] {
  return list(value, max).map((item) => str(item));
}
