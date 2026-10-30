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
