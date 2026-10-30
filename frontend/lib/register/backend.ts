import { fhirFetch, FhirError, type FhirResult } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';
import { callLinkApi, type LinkReply } from '@/lib/links/server';
import { addressesFrom, viewFromRecord, type RecordView } from './applicant';
import type { StepName } from './types';

// The registration seam: the only place the registration BFF routes call the back end.
// Identity routes sit beside /fhir and are tenant-bound from the Host header, so they go through
// lib/links/server (node:http keeps the Host). The FHIR routes go through lib/fhir/client with the
// reporter's bearer token. The applicant's own reads and actions (W7B A1) sit at the back end's
// root with the same bearer token (fhirFetch with root). The browser never names a tenant (DEC-130).

/** The applicant's answer from the back end that the screens cannot use: a 503 that names nothing. */
function unreadable(what: string): FhirError {
  const outcome: OperationOutcome = {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics: `${what} could not be read` }],
  };
  return new FhirError(503, outcome);
}

/** The link as the back end reads it, for the applicant's sign-in (W7B A2, DEC-900). Host-bound, no token. */
export async function readInvitation(host: string | null, invitation: string): Promise<LinkReply> {
  return callLinkApi({ method: 'POST', path: '/identity/invitation', host, body: { invitation } });
}

/** Asks for a code to the number the open invitation holds. The back end answers 202 whether or not a code went. */
export async function requestRegistrationCode(host: string | null, invitation: string): Promise<LinkReply> {
  return callLinkApi({ method: 'POST', path: '/identity/registration/code', host, body: { invitation } });
}

/** Checks a code for the invitation and the device. A right code ends in a reporter token and the registration. */
export async function verifyRegistrationCode(input: {
  host: string | null;
  invitation: string;
  code: string;
  deviceId: string;
}): Promise<LinkReply> {
  return callLinkApi({
    method: 'POST',
    path: '/identity/registration/session',
    host: input.host,
    body: { invitation: input.invitation, code: input.code, deviceId: input.deviceId },
  });
}

async function bearerGet(token: string, path: string): Promise<unknown> {
  const result = await fhirFetch<unknown>(path, { token, root: true });
  return result.data;
}

async function bearerPost(token: string, path: string): Promise<unknown> {
  const result = await fhirFetch<unknown>(path, { method: 'POST', token, root: true, idempotencyKey: crypto.randomUUID() });
  return result.data;
}

/** The applicant's registration: its record, mapped for the screens (W7B A1). Another person's is a 404. */
export async function readRegistration(token: string, id: string): Promise<RecordView> {
  const view = viewFromRecord(await bearerGet(token, `/registrations/${encodeURIComponent(id)}/record`));
  if (view === null) throw unreadable('The registration');
  return view;
}

/**
 * Saves one step's answers as the back end's draft (R10 `PUT /fhir/Task/{id}/$draft`). A partial save
 * is a "Save draft" (DEC-905): the back end keeps what is there and says what is still missing. A
 * refusal is a 400 OperationOutcome, which surfaces as a FhirError for the route to map.
 */
export async function saveStep(
  token: string,
  id: string,
  step: StepName,
  values: Record<string, unknown>,
  partial = false,
): Promise<{ status: string; incomplete: { field: string; message: string }[] }> {
  const result: FhirResult<unknown> = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$draft`, {
    method: 'PUT',
    token,
    body: partial ? { step, values, partial: true } : { step, values },
    idempotencyKey: crypto.randomUUID(),
  });
  return { status: businessStatusOf(result.data), incomplete: incompleteOf(result.data) };
}

function businessStatusOf(task: unknown): string {
  const coding = (task as { businessStatus?: { coding?: { code?: unknown }[] } } | undefined)?.businessStatus?.coding;
  const code = coding?.[0]?.code;
  return typeof code === 'string' ? code : 'draft';
}

function incompleteOf(task: unknown): { field: string; message: string }[] {
  const list = (task as { incomplete?: unknown } | undefined)?.incomplete;
  if (!Array.isArray(list)) return [];
  return list.flatMap((item): { field: string; message: string }[] => {
    const field = (item as { field?: unknown })?.field;
    const message = (item as { message?: unknown })?.message;
    return typeof field === 'string' && typeof message === 'string' ? [{ field, message }] : [];
  });
}

/** The addresses for a postcode, at most twenty: the id and the label (W7B A1). A lookup that cannot answer is a 503. */
export async function readAddresses(token: string, postcode: string): Promise<{ id: string; label: string }[]> {
  const list = addressesFrom(await bearerGet(token, `/addresses?postcode=${encodeURIComponent(postcode)}`));
  if (list === null) throw unreadable('The address lookup');
  return list;
}

/**
 * Submits the registration for approval (R10 `POST /fhir/Task/{id}/$submit`). A refusal is a 400
 * OperationOutcome, a FhirError the route maps to the errors the review shows.
 */
export async function submitRegistration(token: string, id: string): Promise<{ status: string }> {
  const result = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$submit`, {
    method: 'POST',
    token,
    idempotencyKey: crypto.randomUUID(),
  });
  return { status: businessStatusOf(result.data) };
}

/** My registrations, as the back end gives them (mapped by the route with myServicesFrom). */
export async function readMine(token: string): Promise<unknown> {
  return bearerGet(token, '/my/registrations');
}

/** The status answer of one registration, as the back end gives it (mapped by the route with statusFrom). */
export async function readStatus(token: string, id: string): Promise<unknown> {
  return bearerGet(token, `/registrations/${encodeURIComponent(id)}/status`);
}

/** Sends the applicant's test notification (W27; the lead, W29). The back end answers 409 inside a minute. */
export async function sendTestNotification(token: string, id: string): Promise<void> {
  await bearerPost(token, `/registrations/${encodeURIComponent(id)}/test-notification`);
}

/** Asks the shift lead to look again (W27). The back end answers 409 unless submitted or in review. */
export async function askForReview(token: string, id: string): Promise<void> {
  await bearerPost(token, `/registrations/${encodeURIComponent(id)}/review-request`);
}

/** Records that the applicant's details are still right (W27). The back end answers 409 unless a re-check is due. */
export async function confirmDetails(token: string, id: string): Promise<void> {
  await bearerPost(token, `/registrations/${encodeURIComponent(id)}/confirm-details`);
}

export { unreadable };
