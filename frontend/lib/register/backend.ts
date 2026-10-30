import type { Session } from '@/lib/auth/session';
import { fhirFetch, FhirError, type FhirResult } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';
import { callLinkApi, type LinkReply } from '@/lib/links/server';
import type { RegistrationView, StepName } from './types';

// The registration seam: the only place the registration BFF routes call the back end (R10, U25).
// A route the back end does not serve yet throws a 503 with the code `not-built`, so the page shows
// its "could not load" state and nothing is invented. Each such route is named in the W-fragments
// with the back-end route it waits for.
//
// Identity routes sit beside /fhir and are tenant-bound from the Host header, so they go through
// lib/links/server (node:http keeps the Host). The FHIR routes go through lib/fhir/client with the
// reporter's bearer token. The browser never names a tenant (DEC-130, DEC-132).

export type RegistrantSignIn = {
  mobile: string;
  deviceId: string;
  inviteToken: string | undefined;
};

/** The back end's purposes for a code: `setup` is a new device's first sign-in (U25, DEC-413). */
const CODE_PURPOSE_SETUP = 'setup';

/** A route the back end does not serve yet: a 503 the BFF answers with the code `not-built`. */
export function notBuilt(what: string): FhirError {
  const outcome: OperationOutcome = {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'not-built', diagnostics: `${what} is not built in the back end yet` }],
  };
  return new FhirError(503, outcome);
}

/** Asks the back end for a registration code for this mobile. The back end answers 202 for every number. */
export async function sendIdentityCode(host: string | null, mobile: string): Promise<LinkReply> {
  return callLinkApi({ method: 'POST', path: '/identity/code', host, body: { mobile, purpose: CODE_PURPOSE_SETUP } });
}

/** Checks a code for this mobile and device. A right code is recorded on the device by the back end. */
export async function verifyIdentityCode(input: {
  host: string | null;
  mobile: string;
  code: string;
  deviceId: string;
}): Promise<LinkReply> {
  return callLinkApi({
    method: 'POST',
    path: '/identity/code/verify',
    host: input.host,
    body: { mobile: input.mobile, code: input.code, deviceId: input.deviceId, purpose: CODE_PURPOSE_SETUP },
  });
}

/**
 * Signs a verified applicant in: the registration the invitation names, and a reporter session.
 * NOT BUILT: the back end has no reporter token after a text code (the PIN sign-in answers a
 * device session, and the registration routes need a bearer token). Until it does, this throws
 * `not-built`. See docs/delivery/fragments/W23.md.
 */
export async function signInRegistrant(input: RegistrantSignIn): Promise<{ registrationId: string; session: Session }> {
  void input;
  throw notBuilt('The registration sign-in');
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
