import { http, HttpResponse, type RequestHandler } from 'msw';

// Default answers of the practitioner BFF (DEC-1306 to DEC-1309), as the screens parse them. A test overrides
// one with server.use(). The records hold paths, methods, bodies and keys only: never a cookie.

export const seenPractitionerRequests: { path: string; method: string; body: unknown; idempotencyKey?: string | null }[] = [];

export function resetPractitionerRequests() {
  seenPractitionerRequests.length = 0;
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
  seenPractitionerRequests.push({ path: new URL(request.url).pathname, method: request.method, body, ...(key !== null ? { idempotencyKey: key } : {}) });
  return body;
}

export const SHIFT_SAMPLE = {
  status: 'available',
  location: 'never',
  visitsToday: 4,
  next: { id: 'visit-1', sector: 'DT4 8', dueBy: '2026-10-31T14:30:00Z', wantedWithin: 'within 2 hrs' },
  offers: [{ id: 'offer-1', need: 'Fall, no injury', sector: 'DT4 8', wantedWithin: 'within 2 hrs', expiresAt: '2026-10-31T14:34:30Z' }],
  round: [
    { id: 'visit-1', sector: 'DT4 8', state: 'accepted', dueBy: '2026-10-31T14:30:00Z', wantedWithin: 'within 2 hrs' },
    { id: 'visit-2', sector: 'DT1 2', state: 'done', dueBy: null, wantedWithin: 'today' },
  ],
};

export const OFFER_SAMPLE = {
  id: 'offer-1',
  reference: '4821',
  state: 'offered',
  need: 'Fall, no injury',
  sector: 'DT4 8',
  wantedWithin: 'within 2 hrs',
  // Far in the future for the default: a test that wants a countdown sets its own.
  expiresAt: '2099-01-01T00:00:00Z',
  fitsMinutes: null,
  etaAt: null,
  location: 'never',
};

export const VISIT_SAMPLE = {
  ...OFFER_SAMPLE,
  id: 'visit-1',
  state: 'accepted',
  address: '1 Synthetic Street',
  contact: 'Daughter, 07000 000000',
  location: 'travel',
};

const VISITS: Record<string, unknown> = {
  'offer-1': OFFER_SAMPLE,
  'visit-1': VISIT_SAMPLE,
  'done-1': { ...OFFER_SAMPLE, id: 'done-1', state: 'done' },
  'gone-1': { ...OFFER_SAMPLE, id: 'gone-1', state: 'withdrawn' },
};

export const practitionerHandlers: RequestHandler[] = [
  http.get('/api/bff/practitioner/shift', async ({ request }) => {
    await record(request);
    return HttpResponse.json(SHIFT_SAMPLE);
  }),
  http.put('/api/bff/practitioner/settings', async ({ request }) => {
    const body = (await record(request)) as { status?: string | null; location?: string } | undefined;
    return HttpResponse.json({ status: body?.status === undefined ? SHIFT_SAMPLE.status : body.status, location: body?.location ?? SHIFT_SAMPLE.location });
  }),
  http.get('/api/bff/practitioner/visits/:id', async ({ request, params }) => {
    await record(request);
    const found = VISITS[String(params.id)];
    return found === undefined ? HttpResponse.json({ code: 'not-found' }, { status: 404 }) : HttpResponse.json(found as Record<string, unknown>);
  }),
  http.post('/api/bff/practitioner/visits/:id/accept', async ({ request, params }) => {
    await record(request);
    return HttpResponse.json({ id: String(params.id), state: 'accepted' });
  }),
  http.post('/api/bff/practitioner/visits/:id/decline', async ({ request, params }) => {
    await record(request);
    return HttpResponse.json({ id: String(params.id), state: 'declined' });
  }),
  http.post('/api/bff/practitioner/visits/:id/status', async ({ request, params }) => {
    const body = (await record(request)) as { status?: string } | undefined;
    return HttpResponse.json({ id: String(params.id), state: body?.status ?? 'accepted' });
  }),
];
