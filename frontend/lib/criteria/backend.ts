import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { notServed } from '@/lib/registration/backend';
import { mapHistory, waitingVersion } from './history';
import type { CriteriaValues, HistoryVersion, ReviewPeriod } from './types';

// Server-only. The owner's criteria calls to the back end's FHIR API (R10, U30), mapped to the
// browser's shapes. A criteria version is a Basic resource; a change is written straight into
// pending-approval, so the browser's "send" is the change itself (there is no draft store to call).

type Json = Record<string, unknown>;

function badBody(): never {
  throw new FhirError(502, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned a criteria answer that could not be read.' }],
  });
}

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export type ChangeInput = CriteriaValues & { reason: string; reviewInMonths: ReviewPeriod };

/**
 * The change as one Parameters body (U30): the service, the four criteria values, the reason and the
 * review period. Each repeated value is one part, as the back end reads it.
 */
function changeParameters(serviceId: string, input: ChangeInput): Json {
  const parameter: Json[] = [
    { name: 'service', valueReference: { reference: `HealthcareService/${serviceId}` } },
    { name: 'ageMin', valueInteger: input.ageMin },
  ];
  if (input.ageMax !== null) parameter.push({ name: 'ageMax', valueInteger: input.ageMax });
  for (const need of input.accepts) parameter.push({ name: 'accepts', valueCode: need });
  for (const need of input.excludes) parameter.push({ name: 'excludes', valueCode: need });
  for (const district of input.districts) parameter.push({ name: 'district', valueString: district });
  parameter.push({ name: 'changeReason', valueString: input.reason });
  parameter.push({ name: 'reviewMonths', valueInteger: input.reviewInMonths });
  return { resourceType: 'Parameters', parameter };
}

/** The version the back end wrote, from the Basic it returns (its meta.versionId and status). */
function versionOf(data: unknown): { version: number; status: string } {
  if (!isRecord(data) || data.resourceType !== 'Basic') badBody();
  const meta = isRecord(data.meta) ? data.meta : undefined;
  const version = typeof meta?.versionId === 'string' ? Number(meta.versionId) : NaN;
  if (!Number.isInteger(version) || typeof data.status !== 'string') badBody();
  return { version, status: data.status as string };
}

/** The owner's change, written into pending-approval (U30). The approver is someone else (lead). */
export async function submitChange(token: string, serviceId: string, input: ChangeInput, key: string) {
  const { data } = await fhirFetch<unknown>('/Basic', {
    method: 'POST',
    token,
    idempotencyKey: key,
    body: changeParameters(serviceId, input),
  });
  return versionOf(data);
}

/** The review period the owner confirms (U30): 3, 6 or 12 months. */
export async function confirmReview(token: string, serviceId: string, months: ReviewPeriod, key: string) {
  const { data } = await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(serviceId)}/$confirm-criteria`, {
    method: 'POST',
    token,
    idempotencyKey: key,
    body: { resourceType: 'Parameters', parameter: [{ name: 'reviewInMonths', valueInteger: months }] },
  });
  if (!isRecord(data) || !Array.isArray(data.parameter)) badBody();
  const reviewPart = (data.parameter as unknown[]).find((part) => isRecord(part) && part.name === 'reviewBy');
  const reviewBy = isRecord(reviewPart) ? reviewPart.valueDate : undefined;
  if (typeof reviewBy !== 'string') badBody();
  return { reviewBy: reviewBy as string };
}

/** The versions of one service, newest first (U30, `GET /Basic?subject=`). */
export async function readHistory(token: string, serviceId: string): Promise<HistoryVersion[]> {
  const { data } = await fhirFetch<unknown>(`/Basic?subject=${encodeURIComponent(`HealthcareService/${serviceId}`)}`, { token });
  return mapHistory(data);
}

/**
 * The approver's decision on the version waiting for approval (U30): approve it, or send it back with
 * a note. The waiting version is found in the history; the back end refuses the approver who wrote it.
 */
export async function decidePending(
  token: string,
  serviceId: string,
  decision: 'approve' | 'send-back',
  note: string | undefined,
  key: string,
): Promise<{ status: string; version: number }> {
  const waiting = waitingVersion(await readHistory(token, serviceId));
  if (waiting === null) {
    throw new FhirError(404, {
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'not-found', diagnostics: 'There is no version waiting for approval.' }],
    });
  }
  const operation = decision === 'approve' ? '$approve' : '$send-back';
  const body = note === undefined ? undefined : { resourceType: 'Parameters', parameter: [{ name: 'note', valueString: note }] };
  const { data } = await fhirFetch<unknown>(`/Basic/${encodeURIComponent(waiting.criteriaId)}/${operation}`, {
    method: 'POST',
    token,
    idempotencyKey: key,
    body,
  });
  if (!isRecord(data) || typeof data.status !== 'string' || typeof data.meta !== 'object' || data.meta === null) badBody();
  const version = Number((data.meta as Json).versionId);
  if (!Number.isInteger(version)) badBody();
  return { status: data.status as string, version };
}

/** The approver's read of the waiting change. The back end does not serve the change's words, its author or its reason yet (R10). */
export function readPending(): never {
  return notServed();
}

/** The current version and any draft, as the owner's overview. Not served by the back end yet (R10). */
export function readCriteria(): never {
  return notServed();
}
