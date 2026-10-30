// Checks on what the browser may send to the registration BFF routes. Each refusal is a 400 with a
// fixed code and no copy of the value sent (DEC-109 item 2). Pure: no I/O.
import { FhirError } from '@/lib/fhir/client';
import {
  CALLBACK_RESULTS,
  CATEGORY_CODES,
  NAME_MAX_LENGTH,
  NOTE_MAX_LENGTH,
  SCOPE_ANSWERS,
  SCOPE_FLAGS,
  callbackFormError,
  decisionNoteError,
  reasonRequired,
  scopeFormError,
} from './model';
import type { CallBackInput, DecisionAction, ScopeDecisionInput, ScopeEntryInput } from './backend';
import type { CallBackResult, ScopeAnswer, ScopeFlag } from './types';

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

const NUMBER_SHAPE = /^[0-9+ ()-]{6,20}$/;
const DECISION_ACTIONS: readonly DecisionAction[] = ['approve', 'send-back', 'not-approve'];

export function callBackBody(value: unknown): CallBackInput {
  const body = recordOf(value);
  const result = body.result;
  if (typeof result !== 'string' || !(CALLBACK_RESULTS as readonly string[]).includes(result)) badRequest();
  const numberCalled = textOf(body.numberCalled, 20, true) as string;
  if (!NUMBER_SHAPE.test(numberCalled)) badRequest();
  const spokeToRole = textOf(body.spokeToRole, NAME_MAX_LENGTH, false);
  if (callbackFormError(result as CallBackResult, spokeToRole ?? '') !== null) badRequest();
  return { result, numberCalled, ...(spokeToRole !== undefined ? { spokeToRole } : {}) };
}

export function scopeDecisionBody(value: unknown): ScopeDecisionInput {
  const body = recordOf(value);
  const answers = recordOf(body.answers);
  const pick = (key: string): ScopeAnswer => {
    const answer = answers[key];
    if (typeof answer !== 'string' || !(SCOPE_ANSWERS as readonly string[]).includes(answer)) badRequest();
    return answer as ScopeAnswer;
  };
  const decision = body.decision;
  if (typeof decision !== 'string' || !(SCOPE_FLAGS as readonly string[]).includes(decision)) badRequest();
  const reason = textOf(body.reason, NOTE_MAX_LENGTH, false);
  const answered = {
    pathway: pick('pathway'),
    spoaReferrals: pick('spoaReferrals'),
    canReport: pick('canReport'),
    categoryOnList: pick('categoryOnList'),
  };
  if (scopeFormError(answered, decision as ScopeFlag, reason ?? '') !== null) badRequest();
  return { answers: answered, decision: decision as ScopeFlag, ...(reason !== undefined ? { reason } : {}) };
}

export function decisionBody(value: unknown): { action: DecisionAction; note?: string } {
  const body = recordOf(value);
  const action = body.action;
  if (typeof action !== 'string' || !(DECISION_ACTIONS as readonly string[]).includes(action)) badRequest();
  const note = textOf(body.note, NOTE_MAX_LENGTH, false);
  if (decisionNoteError(action as DecisionAction, note ?? '') !== null) badRequest();
  return { action: action as DecisionAction, ...(note !== undefined ? { note } : {}) };
}

export { textOf };
