// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CHECKIN_CSRF_COOKIE } from '@/lib/checkin/server';
import { BACKEND_ROOT, TENANT_HOST } from '@/test/fixtures/links';
import { TEST_SESSION_SECRET, cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { POST as CONFIRM } from './confirm/route';
import { POST as CODE } from './code/route';
import { GET } from './route';

// The check-in page's own API (DEC-1346). No session: the code in the address says which service, and the tenant is the
// host the request was addressed to.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const TOKEN = 'AbCdEfGhIjKlMnOpQrStUvW';
const CSRF = 'csrf-of-this-code';
const url = (path = '') => `https://${TENANT_HOST}/api/bff/checkin/${TOKEN}${path}`;
const ctx = { params: Promise.resolve({ token: TOKEN }) };
const MOBILE = '07700 900111';

let seen: { path: string; host: string | null; csrf: string | null; body: unknown }[] = [];

function backend(path: string, status: number, body: Record<string, unknown>, headers: Record<string, string> = {}) {
  return http.all(`${BACKEND_ROOT}/checkin/:token${path}`, async ({ request }) => {
    const text = await request.text();
    seen.push({
      path: new URL(request.url).pathname,
      host: request.headers.get('host'),
      csrf: request.headers.get('x-csrf-token'),
      body: text === '' ? undefined : (JSON.parse(text) as unknown),
    });
    return HttpResponse.json(body, { status, headers });
  });
}

function write(path: string, body: unknown, cookie: string | null = CSRF, header: string | null = CSRF) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Host: TENANT_HOST };
  if (header !== null) headers['X-CSRF-Token'] = header;
  return requestWithCookies(url(path), cookie === null ? {} : { [CHECKIN_CSRF_COOKIE]: cookie }, {
    method: 'POST',
    headers,
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  seen = [];
  resetCookieWrites();
  cookiesMock.mockClear();
});

describe('GET /api/bff/checkin/[token]', () => {
  it('names the service, sets the CSRF cookie for this code only and sends the request host', async () => {
    server.use(backend('', 200, { service: 'UCR West', csrfToken: CSRF }));

    const response = await GET(requestWithCookies(url(), {}, { headers: { Host: TENANT_HOST } }), ctx);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ service: 'UCR West', csrfToken: CSRF });
    expect(lastWrite(CHECKIN_CSRF_COOKIE)).toMatchObject({
      value: CSRF,
      options: { httpOnly: true, sameSite: 'strict', path: `/api/bff/checkin/${TOKEN}` },
    });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(seen.at(-1)).toMatchObject({ path: `/checkin/${TOKEN}`, host: TENANT_HOST });
  });

  it('answers 410 for a code the back end does not know, and a text that cannot be a code with no request made', async () => {
    server.use(backend('', 410, { state: 'gone' }));

    const unknown = await GET(requestWithCookies(url(), {}), ctx);
    const malformed = await GET(requestWithCookies(url(), {}), { params: Promise.resolve({ token: 'no spaces!' }) });

    expect(unknown.status).toBe(410);
    expect(await unknown.json()).toEqual({ state: 'gone' });
    expect(malformed.status).toBe(410);
    expect(seen).toHaveLength(1);
    expect(cookieWrites).toHaveLength(0);
  });

  it('answers 503 when the back end cannot be reached', async () => {
    server.use(http.get(`${BACKEND_ROOT}/checkin/:token`, () => HttpResponse.error()));
    expect((await GET(requestWithCookies(url(), {}), ctx)).status).toBe(503);
  });
});

describe('POST /api/bff/checkin/[token]/code', () => {
  it('passes on only the number, with the CSRF header, and answers that a code was sent', async () => {
    server.use(backend('/code', 202, { state: 'sent', extra: 'dropped' }));

    const response = await CODE(write('/code', { mobile: MOBILE }), ctx);

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ state: 'sent' });
    expect(seen.at(-1)).toMatchObject({ path: `/checkin/${TOKEN}/code`, csrf: CSRF, host: TENANT_HOST, body: { mobile: MOBILE } });
  });

  it.each([
    ['no cookie', null, CSRF],
    ['no header', CSRF, null],
    ['a header that is not the cookie', CSRF, 'another'],
  ])('answers 403 with %s and asks the back end nothing', async (_name, cookie, header) => {
    server.use(backend('/code', 202, { state: 'sent' }));

    const response = await CODE(write('/code', { mobile: MOBILE }, cookie, header), ctx);

    expect(response.status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it.each([
    ['a number that is not a UK mobile', { mobile: '12345' }],
    ['a field the page does not take', { mobile: MOBILE, tenant: 'x' }],
    ['no number', {}],
    ['text that is not JSON', 'not json'],
  ])('answers 400 for %s', async (_name, body) => {
    server.use(backend('/code', 202, { state: 'sent' }));
    expect((await CODE(write('/code', body), ctx)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('passes on a 429 with its Retry-After', async () => {
    server.use(backend('/code', 429, { state: 'rate-limited' }, { 'Retry-After': '120' }));

    const response = await CODE(write('/code', { mobile: MOBILE }), ctx);

    expect(response.status).toBe(429);
    expect(response.headers.get('Retry-After')).toBe('120');
  });
});

describe('POST /api/bff/checkin/[token]/confirm', () => {
  it('goes on shift: passes on the number, the code, the action and the hours, and answers the service and the end', async () => {
    server.use(backend('/confirm', 200, { state: 'on-shift', service: 'UCR West', until: '18:00' }));

    const response = await CONFIRM(write('/confirm', { mobile: MOBILE, code: '123456', action: 'on', hours: 8 }), ctx);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ state: 'on-shift', service: 'UCR West', until: '18:00' });
    expect(seen.at(-1)).toMatchObject({ path: `/checkin/${TOKEN}/confirm`, csrf: CSRF, body: { mobile: MOBILE, code: '123456', action: 'on', hours: 8 } });
  });

  it('goes off shift with no hours', async () => {
    server.use(backend('/confirm', 200, { state: 'off-shift' }));

    const response = await CONFIRM(write('/confirm', { mobile: MOBILE, code: '123456', action: 'off' }), ctx);

    expect(await response.json()).toEqual({ state: 'off-shift' });
    expect(seen.at(-1)?.body).toEqual({ mobile: MOBILE, code: '123456', action: 'off' });
  });

  it('answers 403 with the CSRF cookie missing', async () => {
    expect((await CONFIRM(write('/confirm', { mobile: MOBILE, code: '123456', action: 'on' }, null, CSRF), ctx)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it.each([
    ['a code that is not digits', { mobile: MOBILE, code: 'abcdef', action: 'on' }],
    ['an action that is neither on nor off', { mobile: MOBILE, code: '123456', action: 'both' }],
    ['hours with going off', { mobile: MOBILE, code: '123456', action: 'off', hours: 4 }],
    ['hours of more than 14', { mobile: MOBILE, code: '123456', action: 'on', hours: 15 }],
    ['hours that are not whole', { mobile: MOBILE, code: '123456', action: 'on', hours: 2.5 }],
    ['a field the page does not take', { mobile: MOBILE, code: '123456', action: 'on', service: 'x' }],
  ])('answers 400 for %s', async (_name, body) => {
    expect((await CONFIRM(write('/confirm', body), ctx)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('passes on a wrong code as a 403 code-wrong, and a gone code as a 410', async () => {
    server.use(backend('/confirm', 403, { state: 'code-wrong' }));
    const wrong = await CONFIRM(write('/confirm', { mobile: MOBILE, code: '000000', action: 'on' }), ctx);
    expect(wrong.status).toBe(403);
    expect(await wrong.json()).toEqual({ state: 'code-wrong' });

    server.use(backend('/confirm', 410, { state: 'gone' }));
    expect((await CONFIRM(write('/confirm', { mobile: MOBILE, code: '000000', action: 'on' }), ctx)).status).toBe(410);
  });

  it('never repeats a number or a code in an answer, and turns an odd status into a fixed one', async () => {
    server.use(backend('/confirm', 418, { state: 'teapot', mobile: MOBILE }));

    const response = await CONFIRM(write('/confirm', { mobile: MOBILE, code: '123456', action: 'on' }), ctx);

    const text = await response.text();
    expect(response.status).toBe(400);
    expect(text).not.toContain('07700');
    expect(text).not.toContain('123456');
  });
});
