// Checks on what the browser may send to the registration BFF routes. Each refusal is a 400 with a
// fixed code and no copy of the value sent (DEC-109 item 2). Pure: no I/O.
import { FhirError } from '@/lib/fhir/client';
import { CATEGORY_CODES, NAME_MAX_LENGTH, NOTE_MAX_LENGTH, SCOPE_FLAGS, reasonRequired } from './model';
import type { ScopeEntryInput } from './backend';
import type { ScopeFlag } from './types';

const KEY_SHAPE = /^[\x21-\x7e]{1,200}$/;
const ID_SHAPE = /^[A-Za-z0-9-]{1,64}$/;

type Json = Record<string, unknown>;

export function badRequest(): never {
  throw new FhirError(400, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'invalid', diagnostics: 'The request was not valid.' }],
  });
}

export function recordOf(value: unknown): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) badRequest();
  return value as Json;
}

/** The idempotency key the browser sent: required on every write (the back end refuses without it). */
export function idempotencyKeyOf(request: Request): string {
  const key = request.headers.get('Idempotency-Key');
  if (key === null || !KEY_SHAPE.test(key)) badRequest();
  return key;
}

/** A registration, service or criteria id from a route segment. */
export function idOf(value: string): string {
  if (!ID_SHAPE.test(value)) badRequest();
  return value;
}

function textOf(value: unknown, max: number, required: boolean): string | undefined {
  if (value === undefined || value === null || value === '') {
    if (required) badRequest();
    return undefined;
  }
  if (typeof value !== 'string') badRequest();
  const trimmed = (value as string).trim();
  if (trimmed === '') {
    if (required) badRequest();
    return undefined;
  }
  if (trimmed.length > max) badRequest();
  return trimmed;
}

export function scopeEntryBody(value: unknown): ScopeEntryInput {
  const body = recordOf(value);
  const name = textOf(body.name, NAME_MAX_LENGTH, true) as string;
  const category = body.category;
  if (typeof category !== 'string' || !CATEGORY_CODES.includes(category)) badRequest();
  const flag = body.flag;
  if (typeof flag !== 'string' || !(SCOPE_FLAGS as readonly string[]).includes(flag)) badRequest();
  const reason = textOf(body.reason, NOTE_MAX_LENGTH, false);
  if (reasonRequired(flag as ScopeFlag) && reason === undefined) badRequest();
  return {
    name,
    category: category as string,
    flag: flag as ScopeFlag,
    ...(reason !== undefined ? { reason } : {}),
  };
}

export { textOf };
