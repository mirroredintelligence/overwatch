import { createHash, randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { parseSaved, pickSubscription } from '@/lib/reporter/answers';
import { badAnswer, json, keyOf, onlyFields, plain, readJson } from '@/lib/reporter/backend';

// POST /api/bff/push/subscriptions (W34, W7B, W8E, DEC-661). Saves the browser's push subscription with
// its consent wording, for the device the session was made on, through `POST /identity/push-subscription`
// with the reporter's token. It is called from the All-set step after the reporter has signed in. The
// device is the session's (the token names it) and never the request's; the subscription is passed on
// and never answered, logged or kept here.
//
// An executive (W9H, DEC-1040, DEC-1042) signs in through the directory, so their session has no device.
// The device their subscription is kept under is derived from the subscription's own endpoint (a stable
// id for that browser: the SHA-256 of the endpoint, 43 base64url characters), never sent by the page. The
// consent wording is the executive's own, because what they are sent is alerts, not capacity requests.
const WORDINGS = { reporter: 'v1', exec: 'exec-v1' } as const;

/** The device an executive's subscription is kept under: stable for the browser, and not a secret it holds. */
function deviceOfEndpoint(endpoint: string): string {
  return createHash('sha256').update(endpoint).digest('base64url');
}

export const POST = withBff(
  async (request, session) => {
    const body = await readJson(request);
    const wording = session.role === 'exec' ? WORDINGS.exec : WORDINGS.reporter;
    if (!onlyFields(body, ['subscription', 'consentWordingVersion']) || body.consentWordingVersion !== wording) return plain(400, 'invalid');
    const subscription = pickSubscription(body.subscription);
    const device = session.role === 'exec' && subscription !== null ? deviceOfEndpoint(subscription.endpoint) : session.device;
    if (subscription === null || device === undefined) return plain(400, 'invalid');
    const { data } = await fhirFetch<unknown>('/identity/push-subscription', {
      method: 'POST',
      token: session.backendToken,
      root: true,
      body: { subscription, wordingVersion: wording, deviceId: device },
      idempotencyKey: keyOf(request) ?? randomUUID(),
    });
    if (parseSaved(data) === null) throw badAnswer();
    return json({ saved: true });
  },
  { roles: ['reporter', 'exec'] },
);
