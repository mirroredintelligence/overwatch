import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { CATEGORY_CODES, SCOPE_FLAGS } from './model';
import type { ScopeEntry, ScopeFlag, ScopeList, ScopeRegistrationState } from './types';

// Server-only. The registration calls to the back end's FHIR API (R10), mapped to the browser's
// shapes. Every path is relative to DIUCS_FHIR_BASE_URL, as lib/board/read.ts does. The token is the
// only thing that says whose registrations these are: no organisation is sent or read (DEC-130).

const SCOPE_EXTENSION = /\/scope-list\/([a-z-]+)$/;

type Json = Record<string, unknown>;

/**
 * A read the back end does not serve yet. Answered as 503 `not-supported`, with no detail in the
 * browser's answer. The BFF routes for these reads are real; the back-end route is what is missing
 * (see the fragment, known issues).
 */
export function notServed(): never {
  throw new FhirError(503, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'not-supported', diagnostics: 'The back end does not serve this read yet.' }],
  });
}

function badBody(): never {
  throw new FhirError(502, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned a list that could not be read.' }],
  });
}

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The state the scope list shows, from the back end's registration status (absent: not invited). */
function stateOf(status: string | undefined): ScopeRegistrationState {
  switch (status) {
    case undefined:
      return 'not-invited';
    case 'invited':
      return 'invited';
    case 'live':
      return 'live';
    case 'paused':
      return 'paused';
    case 'not-approved':
      return 'not-approved';
    case 'reverify':
      return 'reverify';
    default:
      // draft, submitted, in-review, needs-changes, approved: all still under review.
      return 'in-review';
  }
}

/**
 * The back end's scope list (a FHIR List, U23) as the browser reads it. Each entry is an item
 * reference, a flag coding and named extensions. A list that is not a scope list is refused.
 */
export function mapScopeList(list: unknown): ScopeList {
  if (!isRecord(list) || list.resourceType !== 'List' || !Array.isArray(list.entry)) badBody();
  const entries: ScopeEntry[] = [];
  for (const raw of list.entry) {
    if (!isRecord(raw)) badBody();
    const item = isRecord(raw.item) ? raw.item.reference : undefined;
    const flagCoding = isRecord(raw.flag) && Array.isArray(raw.flag.coding) ? raw.flag.coding[0] : undefined;
    const flagCode = isRecord(flagCoding) ? flagCoding.code : undefined;
    if (typeof item !== 'string' || !item.startsWith('HealthcareService/')) badBody();
    if (typeof flagCode !== 'string' || !(SCOPE_FLAGS as readonly string[]).includes(flagCode)) badBody();

    const named = new Map<string, Json>();
    for (const extension of Array.isArray(raw.extension) ? raw.extension : []) {
      if (!isRecord(extension) || typeof extension.url !== 'string') continue;
      const match = SCOPE_EXTENSION.exec(extension.url);
      if (match?.[1] !== undefined) named.set(match[1], extension);
    }
    const text = (name: string): string | undefined => {
      const value = named.get(name)?.valueString;
      return typeof value === 'string' && value !== '' ? value : undefined;
    };
    const code = (name: string): string | undefined => {
      const value = named.get(name)?.valueCode;
      return typeof value === 'string' ? value : undefined;
    };
    const name = text('name');
    const category = code('category');
    if (name === undefined || category === undefined || !CATEGORY_CODES.includes(category)) badBody();

    const reason = text('reason');
    entries.push({
      serviceId: item.slice('HealthcareService/'.length),
      name,
      category,
      flag: flagCode as ScopeFlag,
      registrationState: stateOf(code('registration-status')),
      ...(reason !== undefined ? { reason } : {}),
    });
  }
  return { entries };
}

export async function readScopeList(token: string): Promise<ScopeList> {
  const { data } = await fhirFetch<unknown>('/List/scope-list', { token });
  return mapScopeList(data);
}

export type ScopeEntryInput = { name: string; category: string; flag: ScopeFlag; reason?: string };

/** One $entry (U23): the Parameters the back end reads, built from the four checked fields only. */
export async function addScopeEntry(token: string, input: ScopeEntryInput, key: string): Promise<{ serviceId: string }> {
  const parameter: Json[] = [
    { name: 'service', valueString: input.name },
    { name: 'category', valueCode: input.category },
    { name: 'flag', valueCode: input.flag },
  ];
  if (input.reason !== undefined) parameter.push({ name: 'reason', valueString: input.reason });
  const { data } = await fhirFetch<Json>('/List/scope-list/$entry', {
    method: 'POST',
    token,
    idempotencyKey: key,
    body: { resourceType: 'Parameters', parameter },
  });
  const found = isRecord(data) && Array.isArray(data.parameter) ? data.parameter.find((p) => isRecord(p) && p.name === 'serviceId') : undefined;
  const serviceId = isRecord(found) ? found.valueString : undefined;
  if (typeof serviceId !== 'string') badBody();
  return { serviceId };
}

// ------------------------------------------------------------------------------ W29 writes

export type CallBackInput = { result: string; numberCalled: string; spokeToRole?: string };
export type ScopeDecisionInput = {
  answers: { pathway: string; spoaReferrals: string; canReport: string; categoryOnList: string };
  decision: ScopeFlag;
  reason?: string;
};

/** Parts the back end reads as codes; every other text part is a string. */
const CODE_PARTS: ReadonlySet<string> = new Set([
  'result',
  'flag',
  'onDorsetPathway',
  'takesSpoaReferrals',
  'canReport',
  'categoryOnPilotList',
]);

function parameters(entries: Array<[string, string]>): Json {
  return {
    resourceType: 'Parameters',
    parameter: entries.map(([name, value]) => (CODE_PARTS.has(name) ? { name, valueCode: value } : { name, valueString: value })),
  };
}

/** The named parts of a Parameters answer, as their values. Other parts are not read. */
function partsOf(data: unknown): Map<string, unknown> {
  const found = new Map<string, unknown>();
  if (!isRecord(data) || !Array.isArray(data.parameter)) badBody();
  for (const part of data.parameter as unknown[]) {
    if (!isRecord(part) || typeof part.name !== 'string') continue;
    found.set(part.name, part.valueCode ?? part.valueString ?? part.valueBoolean);
  }
  return found;
}

/** One call-back (U28): the number called, the role spoken to (when there was a call) and the result. */
export async function recordCallBack(token: string, id: string, input: CallBackInput, key: string) {
  const entries: Array<[string, string]> = [['numberCalled', input.numberCalled]];
  if (input.spokeToRole !== undefined) entries.push(['spokeToRole', input.spokeToRole]);
  entries.push(['result', input.result]);
  const { data } = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$callback`, {
    method: 'POST',
    token,
    idempotencyKey: key,
    body: parameters(entries),
  });
  const parts = partsOf(data);
  const result = parts.get('result');
  if (typeof result !== 'string' || typeof parts.get('callbackConfirmed') !== 'boolean') badBody();
  return { result: result as string, callbackConfirmed: parts.get('callbackConfirmed') as boolean };
}

/** The scope decision (U28): four answers, the flag, and the reason when one is needed. */
export async function recordScopeDecision(token: string, id: string, input: ScopeDecisionInput, key: string) {
  const entries: Array<[string, string]> = [
    ['onDorsetPathway', input.answers.pathway],
    ['takesSpoaReferrals', input.answers.spoaReferrals],
    ['canReport', input.answers.canReport],
    ['categoryOnPilotList', input.answers.categoryOnList],
    ['flag', input.decision],
  ];
  if (input.reason !== undefined) entries.push(['reason', input.reason]);
  const { data } = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$scope-decision`, {
    method: 'POST',
    token,
    idempotencyKey: key,
    body: parameters(entries),
  });
  const flag = partsOf(data).get('flag');
  if (typeof flag !== 'string') badBody();
  return { flag: flag as ScopeFlag };
}

export type DecisionAction = 'approve' | 'send-back' | 'not-approve';

const DECISION_OPERATION: Record<DecisionAction, string> = {
  approve: '$approve',
  'send-back': '$send-back',
  'not-approve': '$not-approve',
};

/** The approval, the send back or the refusal (U29). The back end answers the Task's new status. */
export async function decideRegistration(token: string, id: string, action: DecisionAction, note: string | undefined, key: string) {
  const body = action === 'approve' || note === undefined ? undefined : parameters([['note', note]]);
  const { data } = await fhirFetch<Json>(`/Task/${encodeURIComponent(id)}/${DECISION_OPERATION[action]}`, {
    method: 'POST',
    token,
    idempotencyKey: key,
    body,
  });
  return { status: taskStatus(data) };
}

/** The Task's business status code, as the back end writes it. */
function taskStatus(data: unknown): string {
  const coding = isRecord(data) && isRecord(data.businessStatus) && Array.isArray(data.businessStatus.coding) ? data.businessStatus.coding[0] : undefined;
  const code = isRecord(coding) ? coding.code : undefined;
  if (typeof code !== 'string') badBody();
  return code as string;
}

/** The service goes live (U29), once its test is answered. */
export async function setServiceLive(token: string, id: string, key: string) {
  const { data } = await fhirFetch<Json>(`/Task/${encodeURIComponent(id)}/$set-live`, {
    method: 'POST',
    token,
    idempotencyKey: key,
  });
  return { status: taskStatus(data) };
}
