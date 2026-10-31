import { parseScores, type Score } from './scores';
import {
  type CaseInput,
  type CaseView,
  isAgeCode,
  isNeedCode,
  isReferrerCode,
  isUrgencyCode,
  type UrgencyCode,
} from './codes';

// The one mapping between the browser's coded case and the back end's ServiceRequest (R07). Pure:
// no I/O, so both directions are unit-tested against the JSON the back end's own mapping writes
// (case_mapping.py; test/fixtures/backend-shapes.ts).

export const BASE = 'https://diucs.example/';
export const AGE_BAND_EXTENSION = `${BASE}StructureDefinition/age-band`;
export const REFERRER_EXTENSION = `${BASE}StructureDefinition/referrer-type`;
export const URGENCY_EXTENSION = `${BASE}StructureDefinition/urgency`;
export const CLOSED_AT_EXTENSION = `${BASE}StructureDefinition/closed-at`;
export const OUTCOME_EXTENSION = `${BASE}StructureDefinition/outcome`;
// A postcode district chosen on its own (W50, W9H DEC-1045): the back end's `postcode-district` extension on the contained Patient.
export const DISTRICT_EXTENSION = `${BASE}StructureDefinition/postcode-district`;
export const NEED_SYSTEM = `${BASE}CodeSystem/need-category`;
// A referrer's score: one complex extension per score, with its method and value. The back end reads
// and writes this shape (case_mapping.py `_score`, `_score_extension`).
export const SCORE_EXTENSION = `${BASE}StructureDefinition/score`;
// Why a recorded score is changed (sent with the corrected scores) and how many times the scores were
// corrected (read; present only above zero): case_mapping.py SCORE_REASON_EXTENSION, SCORE_CORRECTIONS_EXTENSION.
export const SCORE_REASON_EXTENSION = `${BASE}StructureDefinition/score-correction-reason`;
export const SCORE_CORRECTIONS_EXTENSION = `${BASE}StructureDefinition/score-corrections`;

// The FHIR priority has two values: urgent for within 2 hrs, routine for today and planned. The urgency
// extension carries which of the three it is, and the back end refuses a priority that disagrees with
// it (DEC-773), so a write always sends both.
export function priorityOf(urgency: UrgencyCode): 'urgent' | 'routine' {
  return urgency === 'within-2-hrs' ? 'urgent' : 'routine';
}

function scoreExtension(score: Score): Record<string, unknown> {
  const value =
    typeof score.value === 'number'
      ? { url: 'value', valueInteger: score.value }
      : { url: 'value', valueString: score.value };
  return { url: SCORE_EXTENSION, extension: [{ url: 'method', valueCode: score.method }, value] };
}

type Record_ = Record<string, unknown>;
const asRecord = (value: unknown): Record_ | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record_) : null;

const extensionsOf = (holder: Record_ | null): Record_[] =>
  (Array.isArray(holder?.extension) ? holder.extension : []).map(asRecord).filter((item): item is Record_ => item !== null);

/** The scores on a ServiceRequest, or null when one is not a score the rules allow. */
function scoresOf(request: Record_): Score[] | null {
  const parts = extensionsOf(request)
    .filter((item) => item.url === SCORE_EXTENSION)
    .map((item) => {
      const inner = extensionsOf(item);
      const method = inner.find((part) => part.url === 'method')?.valueCode;
      const valuePart = inner.find((part) => part.url === 'value');
      const value = valuePart?.valueInteger ?? valuePart?.valueString;
      return { method, value };
    });
  return parts.length === 0 ? [] : parseScores(parts);
}

export function toServiceRequest(id: string, input: CaseInput): Record<string, unknown> {
  // The back end keeps the district of a postcode and nothing else of it (DEC-398). With no postcode in
  // the save, the district on record stays as it is, so the Patient carries only the age band.
  const patient: Record<string, unknown> = {
    resourceType: 'Patient',
    id: 'p',
    extension: [{ url: AGE_BAND_EXTENSION, valueCode: input.ageBand }],
  };
  if (input.postcode !== null) patient.address = [{ postalCode: input.postcode }];
  return {
    resourceType: 'ServiceRequest',
    id,
    status: 'active',
    intent: 'plan',
    subject: { reference: '#p' },
    contained: [patient],
    extension: [
      { url: REFERRER_EXTENSION, valueCode: input.referrerType },
      { url: URGENCY_EXTENSION, valueCode: input.urgency },
      ...input.scores.map(scoreExtension),
      ...(input.scoreCorrectionReason ? [{ url: SCORE_REASON_EXTENSION, valueCode: input.scoreCorrectionReason }] : []),
    ],
    priority: priorityOf(input.urgency),
    reasonCode: input.needs.map((need) => ({ coding: [{ system: NEED_SYSTEM, code: need }] })),
  };
}

function codeOf(holder: Record_ | null, url: string): unknown {
  return extensionsOf(holder).find((item) => item.url === url)?.valueCode;
}

function urgencyOf(request: Record_): UrgencyCode | null {
  // The extension says which of the three it is; the priority alone cannot tell today from planned.
  const code = codeOf(request, URGENCY_EXTENSION);
  if (code !== undefined) return isUrgencyCode(code) ? code : null;
  if (request.priority === 'urgent') return 'within-2-hrs';
  if (request.priority === 'routine') return 'today';
  return null;
}

/** The number of corrections on the request: a whole number from zero, else none (never a guess). */
function correctionsOf(request: Record_): number {
  const value = extensionsOf(request).find((item) => item.url === SCORE_CORRECTIONS_EXTENSION)?.valueInteger;
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : 0;
}

function instantOf(value: unknown): string | null {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? value : null;
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

  const needs = (Array.isArray(request.reasonCode) ? request.reasonCode : []).flatMap((concept) => {
    const codings = Array.isArray(asRecord(concept)?.coding) ? (asRecord(concept)?.coding as unknown[]) : [];
    return codings
      .map(asRecord)
      .filter((coding) => coding?.system === NEED_SYSTEM && typeof coding.code === 'string')
      .map((coding) => coding?.code as string);
  });

  const reference = (Array.isArray(request.identifier) ? request.identifier : [])
    .map(asRecord)
    .find((item) => typeof item?.value === 'string')?.value;
  const referrer = codeOf(request, REFERRER_EXTENSION);
  const ageBand = codeOf(patient, AGE_BAND_EXTENSION);
  const outcome = codeOf(request, OUTCOME_EXTENSION);
  const closedAt = extensionsOf(request).find((item) => item.url === CLOSED_AT_EXTENSION)?.valueDateTime;
  const scores = scoresOf(request);
  if (scores === null) return null;
  return {
    id: request.id,
    reference: typeof reference === 'string' ? reference : null,
    referrerType: isReferrerCode(referrer) ? referrer : null,
    ageBand: isAgeCode(ageBand) ? ageBand : null,
    postcode,
    needs: needs.filter(isNeedCode),
    urgency: urgencyOf(request),
    scores,
    scoreCorrections: correctionsOf(request),
    openedAt: instantOf(request.authoredOn),
    closed: request.status === 'completed',
    closedAt: instantOf(closedAt),
    outcome: typeof outcome === 'string' ? outcome : null,
    etag,
  };
}
