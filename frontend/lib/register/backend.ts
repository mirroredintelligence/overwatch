import { FhirError } from '@/lib/fhir/client';
import type { OperationOutcome } from '@/lib/fhir/types';
import type { Session } from '@/lib/auth/session';
import { callLinkApi, type LinkReply } from '@/lib/links/server';

// The registration seam: the only place the registration BFF routes call the back end (R10, U25).
// Routes that the back end does not serve yet throw a 503 with the code `not-built`, so the page
// shows its "could not load" state and nothing is invented. Every such route is named in
// docs/delivery/fragments/W23.md (and the later W-fragments), with the back-end route it waits for.
//
// Identity routes sit beside /fhir and are tenant-bound from the Host header, so they go through
// lib/links/server (node:http keeps the Host). The browser never names a tenant (DEC-130, DEC-132).

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

// Stubs (red commit) for the registration reads and the step save (W54).
import type { RegistrationView, StepName } from './types';

export async function readRegistration(_token: string, _id: string): Promise<RegistrationView> {
  throw notBuilt('The registration read');
}

export async function saveStep(_token: string, _id: string, _step: StepName, _values: Record<string, unknown>): Promise<{ status: string }> {
  throw new Error('not implemented');
}
