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
    return HttpResponse.json(params.token === 'expired-token' ? { ...INVITATION, state: 'expired' } : INVITATION);
  }),
  http.post('/api/bff/identity/code', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ resendAfterSeconds: 60 }, { status: 202 });
  }),
  http.post('/api/bff/identity/code/verify', async ({ request }) => {
    const body = (await record(request)) as { code?: string } | undefined;
    if (body?.code === '000000' || body?.code === '000001' || body?.code === '000002') {
      return HttpResponse.json({ ok: false, triesLeft: body.code === '000002' ? 0 : 4 });
    }
    return HttpResponse.json({ ok: true });
  }),
  http.post('/api/bff/reporter/channel', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true });
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
    HttpResponse.json({ service: 'UCR West', contactBy: 'App notification', maskedPhone: '07xxx xxx456', nextUpdateDue: '12:00', textCodeInDays: 30 }),
  ),
  http.post('/api/bff/push/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ sent: true });
  }),
  http.get('/api/bff/reporter/services/:serviceId/prompt', () =>
    HttpResponse.json({
      service: 'UCR West',
      unitLabel: 'referrals in the next 2 hrs',
      recordedValue: 3,
      asOf: '08:15',
      low: 0,
      high: 8,
      replyBy: '10:30',
      nextDue: '12:00',
    }),
  ),
  http.post('/api/bff/reporter/services/:serviceId/report', async ({ request }) => {
    const body = (await record(request)) as { kind?: string; value?: number } | undefined;
    if (body?.kind === 'number' && typeof body.value === 'number' && body.value > 8) {
      return HttpResponse.json({ result: 'outOfRange', value: body.value });
    }
    const value = body?.kind === 'number' ? body.value : 3;
    return HttpResponse.json({ result: 'recorded', value, recordedAt: '10:12', nextDue: '12:00' });
  }),
  http.get('/api/bff/reporter/services/:serviceId/history', () =>
    HttpResponse.json({
      items: [
        { at: '08:15', value: 2 },
        { at: '10:12', value: 3 },
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
      replyBy: '14:26',
      status: 'requested',
      multiService: false,
      spoaPhone: '0300 000 0000',
    }),
  ),
  http.post('/api/bff/reporter/bookings/:ref/respond', async ({ request }) => {
    const body = (await record(request)) as { decision?: string } | undefined;
    return HttpResponse.json(
      body?.decision === 'decline'
        ? { status: 'declined', at: '14:19' }
        : { status: 'confirmed', confirmedAt: '14:19' },
    );
  }),
  http.post('/api/bff/reporter/cover', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true });
  }),
  http.get('/api/bff/reporter/services', () =>
    HttpResponse.json({
      services: [
        { id: 'svc-west', name: 'UCR West', letter: 'A', state: 'due', recordedValue: 3, unitLabel: 'referrals', at: '08:15', nextDue: '12:00', replyBy: '10:30', pendingAcceptance: false },
        { id: 'svc-east', name: 'UCR East', letter: 'B', state: 'due', recordedValue: 1, unitLabel: 'referral', at: '08:15', nextDue: '12:00', replyBy: '10:30', pendingAcceptance: false },
      ],
    }),
  ),
  http.post('/api/bff/reporter/reports/batch', async ({ request }) => {
    const body = (await record(request)) as { items?: { serviceId: string; kind: string }[] } | undefined;
    return HttpResponse.json({
      results: (body?.items ?? []).map((item) => ({ serviceId: item.serviceId, result: 'recorded', at: '10:12' })),
    });
  }),
  http.post('/api/bff/reporter/services/:serviceId/accept', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true });
  }),
  http.post('/api/bff/reporter/services/:serviceId/cover', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true });
  }),
  http.get('/api/bff/reporter/start', () => HttpResponse.json({ csrfToken: 'T'.repeat(43) })),
];
