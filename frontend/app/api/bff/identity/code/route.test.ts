// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PENDING_COOKIE } from '@/lib/register/pending';
import { BACKEND_ROOT, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { backendIdentity, seenBackendIdentity } from '@/test/msw/handlers/registration';
import { server } from '@/test/msw/server';
import { POST } from './route';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The BFF's code request (W23). No session: the phone is the only thing that says who this is.
// The back end answers 202 for every number; the BFF keeps the invitation and a device id in a
// sealed cookie the browser cannot read, and never forwards a field it does not name.

const URL_ = `https://${TENANT_HOST}/api/bff/identity/code`;
const INVITE = 'InviteTokenSampleValue1';

function post(body: unknown, headers: Record<string, string> = {}) {
  return requestWithCookies(URL_, {}, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Host: TENANT_HOST, ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
  seenBackendIdentity.length = 0;
  backendIdentity.code = { status: 202, body: { accepted: true, resendAfterSeconds: 60 } };
});

describe('POST /api/bff/identity/code', () => {
  it('asks the back end for a registration code for the digits of the number, with the tenant host', async () => {
    const response = await POST(post({ phone: '07700900456', purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ accepted: true, resendAfterSeconds: 60 });
    expect(seenBackendIdentity).toHaveLength(1);
    expect(seenBackendIdentity[0]).toMatchObject({
      path: '/identity/code',
      host: TENANT_HOST,
      body: { mobile: '07700900456', purpose: 'setup' },
    });
  });

  it('keeps the invitation and a device id in a sealed cookie the browser cannot read, and no tenant in it', async () => {
    await POST(post({ phone: '07700 900456', purpose: 'registration', inviteToken: INVITE }));
    const write = lastWrite(PENDING_COOKIE);
    expect(write).toBeDefined();
    expect(write?.value).not.toContain(INVITE);
    expect(write?.value).not.toContain('07700');
    expect(write?.options).toMatchObject({ httpOnly: true, sameSite: 'strict', path: '/api/bff/identity' });
    expect(cookieWrites.map((w) => w.name)).toEqual([PENDING_COOKIE]);
  });

  it('refuses a body that names a tenant, a role or anything else, without calling the back end', async () => {
    for (const extra of [{ tenantId: 'tenant-b' }, { role: 'lead' }, { host: 'other.example.test' }]) {
      const response = await POST(post({ phone: '07700900456', purpose: 'registration', inviteToken: INVITE, ...extra }));
      expect(response.status).toBe(400);
      expect(await response.json()).toMatchObject({ code: 'invalid' });
    }
    expect(seenBackendIdentity).toHaveLength(0);
  });

  it('refuses a number that is not a UK mobile, an unknown purpose or a bad invitation shape, without calling the back end', async () => {
    const bad = [
      { phone: '01305 123456', purpose: 'registration', inviteToken: INVITE },
      { phone: '07700900456', purpose: 'setup', inviteToken: INVITE },
      { phone: '07700900456', purpose: 'registration', inviteToken: 'not a token!' },
      'not json',
    ];
    for (const body of bad) {
      const response = await POST(post(body));
      expect(response.status).toBe(400);
    }
    expect(seenBackendIdentity).toHaveLength(0);
  });

  it('passes the back end’s 429 on, with its Retry-After, and writes no cookie for a refused request', async () => {
    backendIdentity.code = { status: 429, body: { issue: [] }, headers: { 'Retry-After': '600' } };
    server.use(
      http.post(`${BACKEND_ROOT}/identity/code`, (() => HttpResponse.json({}, { status: 429, headers: { 'Retry-After': '600' } })) as HttpResponseResolver),
    );
    const response = await POST(post({ phone: '07700900456', purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(429);
    expect(response.headers.get('Retry-After')).toBe('600');
    expect(await response.json()).toMatchObject({ code: 'throttled' });
  });

  it('answers 503 when the back end cannot be reached, with no detail', async () => {
    server.use(http.post(`${BACKEND_ROOT}/identity/code`, (() => HttpResponse.error()) as HttpResponseResolver));
    const response = await POST(post({ phone: '07700900456', purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(503);
    const text = await response.text();
    expect(text).not.toContain('07700');
    expect(text).not.toContain(INVITE);
  });
});
