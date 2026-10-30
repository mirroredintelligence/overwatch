import { http, HttpResponse, type RequestHandler } from 'msw';

// Default answers of the reporter BFF (W33 to W55). A test overrides one with server.use().
// The records hold paths and bodies only, never a cookie, a device id or a phone number.

export const seenBffRequests: { path: string; method: string; body: unknown; idempotencyKey?: string | null }[] = [];

export function resetReporterRequests() {
  seenBffRequests.length = 0;
}

async function record(request: Request) {
  const text = await request.text();
  let body: unknown = undefined;
  try {
    body = text ? (JSON.parse(text) as unknown) : undefined;
  } catch {
    body = text;
  }
  const key = request.headers.get('Idempotency-Key');
  seenBffRequests.push({
    path: new URL(request.url).pathname,
    method: request.method,
    body,
    ...(key !== null ? { idempotencyKey: key } : {}),
  });
  return body;
}

const INVITATION = {
  service: 'UCR West',
  role: 'reporter',
  maskedPhone: '07xxx xxx456',
  expiresAt: '2026-11-01T10:00:00Z',
  state: 'valid',
} as const;

export const reporterHandlers: RequestHandler[] = [
  http.get('/api/bff/invitations/:token', async ({ request, params }) => {
    await record(request);
    // The BFF's answers (W8E): a valid invitation with its fields, or the one 410 for anything unusable.
    return params.token === 'expired-token' ? HttpResponse.json({ state: 'expired' }, { status: 410 }) : HttpResponse.json(INVITATION);
  }),
  // The text codes of set-up, the 30-day check and a PIN reset (W8E): the browser holds a link's token or
  // the phone's device cookie, never a number.
  http.post('/api/bff/identity/invitation-code', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ accepted: true, resendAfterSeconds: 60 }, { status: 202 });
  }),
  http.post('/api/bff/identity/device-code', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ accepted: true, resendAfterSeconds: 60 }, { status: 202 });
  }),
  ...['/api/bff/identity/invitation-code/verify', '/api/bff/identity/device-code/verify'].map((path) =>
    http.post(path, async ({ request }) => {
      const body = (await record(request)) as { code?: string } | undefined;
      if (body?.code === '000000' || body?.code === '000001' || body?.code === '000002') {
        return HttpResponse.json({ ok: false, triesLeft: body.code === '000002' ? 0 : 4 });
      }
      return HttpResponse.json({ ok: true });
    }),
  ),
  http.post('/api/bff/identity/channel', async ({ request }) => {
    const body = (await record(request)) as { channel?: string } | undefined;
    return HttpResponse.json({ ok: true, channel: body?.channel });
  }),
  http.post('/api/bff/reporter/channel', async ({ request }) => {
    const body = (await record(request)) as { channel?: string } | undefined;
    return HttpResponse.json({ ok: true, channel: body?.channel });
  }),
  http.post('/api/bff/identity/pin', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ pinSet: true });
  }),
  http.post('/api/bff/identity/pin/verify', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true });
  }),
  http.post('/api/bff/push/subscriptions', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ saved: true });
  }),
  http.get('/api/bff/push/key', () => HttpResponse.json({ publicKey: 'BPublicKeyValueSample' })),
  http.get('/api/bff/reporter/setup-summary', () =>
    HttpResponse.json({ service: 'UCR West', contactBy: 'app', maskedPhone: '07xxx xxx456', nextUpdateDue: '2026-10-30T12:00:00Z', textCodeInDays: 30 }),
  ),
  http.post('/api/bff/push/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ queued: true });
  }),
  http.get('/api/bff/reporter/services/:serviceId/prompt', () =>
    HttpResponse.json({
      service: 'UCR West',
      unitLabel: 'referrals in the next 2 hrs',
      recordedValue: 3,
      asOf: '2026-10-30T08:15:00Z',
      low: 0,
      high: 8,
      replyBy: '2026-10-30T10:30:00Z',
      nextDue: '2026-10-30T12:00:00Z',
    }),
  ),
  http.post('/api/bff/reporter/services/:serviceId/report', async ({ request }) => {
    const body = (await record(request)) as { kind?: string; value?: number } | undefined;
    if (body?.kind === 'number' && typeof body.value === 'number' && body.value > 8) {
      return HttpResponse.json({ result: 'outOfRange', serviceName: 'UCR West', value: body.value, low: 0, high: 8 });
    }
    const value = body?.kind === 'number' ? body.value : 3;
    return HttpResponse.json({ result: 'recorded', serviceName: 'UCR West', value, recordedAt: '2026-10-30T10:12:00Z', nextDue: '2026-10-30T12:00:00Z' });
  }),
  http.get('/api/bff/reporter/services/:serviceId/history', () =>
    HttpResponse.json({
      items: [
        { at: '2026-10-30T08:15:00Z', value: 2, kind: 'confirm' },
        { at: '2026-10-30T10:12:00Z', value: 3, kind: 'number' },
      ],
    }),
  ),
  http.get('/api/bff/reporter/bookings/:ref', () =>
    HttpResponse.json({
      reference: '4821',
      service: 'UCR West',
      ageBand: '80+',
      need: 'Fall and frailty',
      urgency: 'Wanted Within 2 hrs',
      replyBy: '2026-10-30T14:26:00Z',
      status: 'requested',
      bookingStatus: 'requested',
      multiService: false,
      spoaPhone: '0300 000 0000',
    }),
  ),
  http.post('/api/bff/reporter/bookings/:ref/respond', async ({ request }) => {
    const body = (await record(request)) as { decision?: string } | undefined;
    return HttpResponse.json(
      body?.decision === 'decline'
        ? { status: 'declined' }
        : { status: 'confirmed', confirmedAt: '2026-10-30T14:19:00Z' },
    );
  }),
  http.post('/api/bff/reporter/cover', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ coveredUntil: '2026-11-06T23:59:00Z', services: 2 });
  }),
  http.get('/api/bff/reporter/services', () =>
    HttpResponse.json({
      services: [
        { id: 'svc-west', name: 'UCR West', letter: 'A', state: 'due', recordedValue: 3, unitLabel: 'referrals', at: '2026-10-30T08:15:00Z', nextDue: '2026-10-30T12:00:00Z', replyBy: '2026-10-30T10:30:00Z', pendingAcceptance: false },
        { id: 'svc-east', name: 'UCR East', letter: 'B', state: 'due', recordedValue: 1, unitLabel: 'referral', at: '2026-10-30T08:15:00Z', nextDue: '2026-10-30T12:00:00Z', replyBy: '2026-10-30T10:30:00Z', pendingAcceptance: false },
      ],
    }),
  ),
  http.post('/api/bff/reporter/reports/batch', async ({ request }) => {
    const body = (await record(request)) as { items?: { serviceId: string; kind: string }[] } | undefined;
    return HttpResponse.json({
      results: (body?.items ?? []).map((item) => ({ serviceId: item.serviceId, result: 'recorded', at: '2026-10-30T10:12:00Z' })),
    });
  }),
  http.post('/api/bff/reporter/services/:serviceId/accept', async ({ request }) => {
    const body = (await record(request)) as { accept?: boolean } | undefined;
    return HttpResponse.json({ accepted: body?.accept === true });
  }),
  http.post('/api/bff/reporter/services/:serviceId/cover', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ coveredUntil: '2026-10-30T23:59:00Z', services: 1 });
  }),
  http.post('/api/bff/identity/new-phone', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ accepted: true, resendAfterSeconds: 60 }, { status: 202 });
  }),
  http.post('/api/bff/identity/new-phone/verify', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ status: 'pending-callback', spoaPhone: '01632 960001' });
  }),
  http.get('/api/bff/reporter/settings', () =>
    HttpResponse.json({ channel: 'text', maskedPhone: '07xxx xxx456', maskedCover: null, reverifyInDays: 21, otherDevices: 1 }),
  ),
  http.post('/api/bff/identity/sign-out-everywhere', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ signedOut: 2 });
  }),
  http.delete('/api/bff/session', () => new HttpResponse(null, { status: 204 })),
  http.get('/api/bff/reporter/start', () => HttpResponse.json({ csrfToken: 'T'.repeat(43) })),
];
