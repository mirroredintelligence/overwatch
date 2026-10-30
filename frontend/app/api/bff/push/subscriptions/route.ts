import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { parseSaved, pickSubscription } from '@/lib/reporter/answers';
import { badAnswer, json, keyOf, onlyFields, plain, readJson } from '@/lib/reporter/backend';

// POST /api/bff/push/subscriptions (W34, W7B, W8E, DEC-661). Saves the browser's push subscription with
// its consent wording, for the device the session was made on, through `POST /identity/push-subscription`
// with the reporter's token. It is called from the All-set step after the reporter has signed in. The
// device is the session's (the token names it) and never the request's; the subscription is passed on
// and never answered, logged or kept here.
const WORDING = 'v1';

export const POST = withBff(
  async (request, session) => {
    const body = await readJson(request);
    if (!onlyFields(body, ['subscription', 'consentWordingVersion']) || body.consentWordingVersion !== WORDING) return plain(400, 'invalid');
    const subscription = pickSubscription(body.subscription);
    if (subscription === null || session.device === undefined) return plain(400, 'invalid');
    const { data } = await fhirFetch<unknown>('/identity/push-subscription', {
      method: 'POST',
      token: session.backendToken,
      root: true,
      body: { subscription, wordingVersion: WORDING, deviceId: session.device },
      idempotencyKey: keyOf(request) ?? randomUUID(),
    });
    if (parseSaved(data) === null) throw badAnswer();
    return json({ saved: true });
  },
  { roles: ['reporter'] },
);
