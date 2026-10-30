import {
  type CaseInput,
  type CaseView,
  isAgeCode,
  isNeedCode,
  isReferrerCode,
  type UrgencyCode,
} from './codes';

// The one mapping between the browser's coded case and the back end's ServiceRequest (R07). Pure:
// no I/O, so both directions are unit-tested. The shapes are the ones routes_cases.py reads and writes.

export const BASE = 'https://diucs.example/';
export const AGE_BAND_EXTENSION = `${BASE}StructureDefinition/age-band`;
export const REFERRER_EXTENSION = `${BASE}StructureDefinition/referrer-type`;
export const NEED_SYSTEM = `${BASE}CodeSystem/need-category`;

// The back end has two priorities. A within-2-hrs case is urgent; today and planned are routine,
// because the back end answers planned as routine (DEC-397). A planned case reads back as today.
export function priorityOf(urgency: UrgencyCode): 'urgent' | 'routine' {
  return urgency === 'within-2-hrs' ? 'urgent' : 'routine';
}

export function toServiceRequest(id: string, input: CaseInput): Record<string, unknown> {
  return {
    resourceType: 'ServiceRequest',
    id,
    status: 'active',
    intent: 'plan',
    subject: { reference: '#p' },
    contained: [
      {
        resourceType: 'Patient',
        id: 'p',
        address: [{ postalCode: input.postcode }],
        extension: [{ url: AGE_BAND_EXTENSION, valueCode: input.ageBand }],
      },
    ],
    extension: [{ url: REFERRER_EXTENSION, valueCode: input.referrerType }],
    priority: priorityOf(input.urgency),
    reasonCode: input.needs.map((need) => ({ coding: [{ system: NEED_SYSTEM, code: need }] })),
  };
}

type Record_ = Record<string, unknown>;
const asRecord = (value: unknown): Record_ | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record_) : null;

function extensionValue(holder: Record_ | null, url: string): unknown {
  const found = (Array.isArray(holder?.extension) ? holder.extension : []).find(
    (item) => asRecord(item)?.url === url,
  );
  return asRecord(found)?.valueCode;
}

/**
 * The browser's view of a ServiceRequest. Unknown or missing parts become null, never a guess. Null
 * when the answer is not a ServiceRequest at all (the caller answers 502).
 */
export function fromServiceRequest(value: unknown, etag: string | null): CaseView | null {
  const request = asRecord(value);
  if (request === null || request.resourceType !== 'ServiceRequest' || typeof request.id !== 'string') return null;

  const patient = (Array.isArray(request.contained) ? request.contained : [])
    .map(asRecord)
    .find((item) => item?.resourceType === 'Patient') ?? null;
  const address = asRecord(Array.isArray(patient?.address) ? patient?.address[0] : null);
  const postcode = typeof address?.postalCode === 'string' ? address.postalCode : null;

  const priority = request.priority;
  const urgency = priority === 'urgent' ? 'within-2-hrs' : priority === 'routine' ? 'today' : null;

  const needs = (Array.isArray(request.reasonCode) ? request.reasonCode : []).flatMap((concept) => {
    const codings = Array.isArray(asRecord(concept)?.coding) ? (asRecord(concept)?.coding as unknown[]) : [];
    return codings
      .map(asRecord)
      .filter((coding) => coding?.system === NEED_SYSTEM && typeof coding.code === 'string')
      .map((coding) => coding?.code as string);
  });

  const referrer = extensionValue(request, REFERRER_EXTENSION);
  const ageBand = extensionValue(patient, AGE_BAND_EXTENSION);
  return {
    id: request.id,
    referrerType: isReferrerCode(referrer) ? referrer : null,
    ageBand: isAgeCode(ageBand) ? ageBand : null,
    postcode,
    needs: needs.filter(isNeedCode),
    urgency: urgency === null ? null : (urgency as UrgencyCode),
    scores: [],
    openedAt: null,
    etag,
  };
}
