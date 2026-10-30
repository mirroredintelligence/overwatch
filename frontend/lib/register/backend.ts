import { fhirFetch, FhirError, type FhirResult } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';
import { callLinkApi, type LinkReply } from '@/lib/links/server';
import type { RegistrationView, StepName } from './types';

// The registration seam: the only place the registration BFF routes call the back end.
// Identity routes sit beside /fhir and are tenant-bound from the Host header, so they go through
// lib/links/server (node:http keeps the Host). The FHIR routes go through lib/fhir/client with the
// reporter's bearer token. The browser never names a tenant (DEC-130, DEC-132).

/** A route the back end does not serve yet: a 503 the BFF answers with the code `not-built`. */
export function notBuilt(what: string): FhirError {
  const outcome: OperationOutcome = {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'not-built', diagnostics: `${what} is not built in the back end yet` }],
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

/**
 * The registration as the back end holds it. NOT BUILT: no route serves a registration read yet
 * (R10 has the draft and the submit only). A 503 `not-built` until one does (W54 fragment).
 */
export async function readRegistration(token: string, id: string): Promise<RegistrationView> {
  void token;
  void id;
  throw notBuilt('The registration read');
}

/**
 * Saves one step's answers as the back end's draft (R10 `PUT /fhir/Task/{id}/$draft`). A refusal
 * is a 400 OperationOutcome, which surfaces as a FhirError for the route to map.
 */
export async function saveStep(token: string, id: string, step: StepName, values: Record<string, unknown>): Promise<{ status: string }> {
  const result: FhirResult<unknown> = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$draft`, {
    method: 'PUT',
    token,
    body: { step, values },
    idempotencyKey: crypto.randomUUID(),
  });
  return { status: businessStatusOf(result.data) };
}

function businessStatusOf(task: unknown): string {
  const coding = (task as { businessStatus?: { coding?: { code?: unknown }[] } } | undefined)?.businessStatus?.coding;
  const code = coding?.[0]?.code;
  return typeof code === 'string' ? code : 'draft';
}

/** NOT BUILT: no address lookup route in the back end (I12 is an adapter; no REST route calls it). */
export async function readAddresses(token: string, postcode: string): Promise<{ id: string; label: string }[]> {
  void token;
  void postcode;
  throw notBuilt('The address lookup');
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

/** NOT BUILT: no route serves the review yet (the back end has the review's use case, not its read). */
export async function readReview(token: string, id: string): Promise<{ key: string; status: string; summary: string }[]> {
  void token;
  void id;
  throw notBuilt('The registration review');
}

/** NOT BUILT: no route lists a reporter's services yet. */
export async function readMine(token: string): Promise<{ id: string; serviceName: string; state: string; detail: string }[]> {
  void token;
  throw notBuilt('The list of my services');
}

/** NOT BUILT: no route serves a registration's status for its applicant yet. */
export async function readStatus(token: string, id: string): Promise<Record<string, unknown>> {
  void token;
  void id;
  throw notBuilt('The registration status');
}

/** NOT BUILT: no route sends the applicant's test notification yet. */
export async function sendTestNotification(token: string, id: string): Promise<void> {
  void token;
  void id;
  throw notBuilt('The test notification');
}

/** NOT BUILT: no route asks the shift lead to look again yet. */
export async function askForReview(token: string, id: string): Promise<void> {
  void token;
  void id;
  throw notBuilt('The review request');
}

/** NOT BUILT: no route records that the applicant's details are still right yet. */
export async function confirmDetails(token: string, id: string): Promise<void> {
  void token;
  void id;
  throw notBuilt('The details confirmation');
}
