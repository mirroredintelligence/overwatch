import { http, HttpResponse, type RequestHandler } from 'msw';

// Default answers of the reporter BFF (W33 to W55). A test overrides one with server.use().
// The records hold paths and bodies only, never a cookie, a device id or a phone number.

export const seenBffRequests: { path: string; method: string; body: unknown }[] = [];

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
  seenBffRequests.push({ path: new URL(request.url).pathname, method: request.method, body });
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
  http.get('/api/bff/reporter/start', () => HttpResponse.json({ csrfToken: 'T'.repeat(43) })),
];
