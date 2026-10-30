// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { notBuilt, signInRegistrant } from '@/lib/register/backend';
import { PENDING_COOKIE, sealPending } from '@/lib/register/pending';
import { BACKEND_ROOT, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { backendIdentity, seenBackendIdentity } from '@/test/msw/handlers/registration';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { server } from '@/test/msw/server';
import { POST } from './route';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The mobile is not built into the back end's sign-in yet (lib/register/backend.ts): the sign-in is
// the seam, mocked here. Everything before it (the back end's code check, the pending cookie, the
// refusals and the cookie the BFF writes) is tested against the real call.
vi.mock('@/lib/register/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/register/backend')>()),
  signInRegistrant: vi.fn(),
}));

const URL_ = `https://${TENANT_HOST}/api/bff/identity/code/verify`;
const INVITE = 'InviteTokenSampleValue1';
const DEVICE = 'Dev1ceIdSampleValue_ab';

const signIn = vi.mocked(signInRegistrant);

async function withPending(): Promise<string> {
  return sealPending({ deviceId: DEVICE, inviteToken: INVITE });
}

function post(body: unknown, cookies: Record<string, string> = {}) {
  return requestWithCookies(URL_, cookies, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Host: TENANT_HOST },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
  seenBackendIdentity.length = 0;
  backendIdentity.verify = { status: 200, body: { verified: true } };
  signIn.mockReset();
  signIn.mockResolvedValue({
    registrationId: 'REG-SAMPLE-1',
    session: sessionFor(TENANTS.A, 'reporter', { sub: 'person-sample-1', backendToken: 'backend-token-sample-value' }),
  });
});

describe('POST /api/bff/identity/code/verify', () => {
  it('checks the code with the back end for the device and the number the code request kept', async () => {
    const pending = await withPending();
    await POST(post({ phone: '07700 900456', code: '123456' }, { [PENDING_COOKIE]: pending }));
    expect(seenBackendIdentity).toHaveLength(1);
    expect(seenBackendIdentity[0]).toMatchObject({
      path: '/identity/code/verify',
      host: TENANT_HOST,
      body: { mobile: '07700900456', code: '123456', deviceId: DEVICE, purpose: 'setup' },
    });
  });

  it('signs in on a right code: the session cookie is HTTP-only, the JSON carries no token, and the pending cookie is cleared', async () => {
    const response = await POST(post({ phone: '07700900456', code: '123456' }, { [PENDING_COOKIE]: await withPending() }));
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({ registrationId: 'REG-SAMPLE-1' });
    expect(JSON.stringify(body)).not.toContain('backend-token');

    const session = lastWrite(SESSION_COOKIE);
    expect(session).toMatchObject({ options: { httpOnly: true, sameSite: 'strict', path: '/' } });
    // The session is the tenant's and the host's the code came to: it is read on that host only.
    expect(await unsealSession(session?.value ?? '')).toMatchObject({ role: 'reporter', services: [], tenantId: TENANTS.A.id, host: TENANTS.A.host });

    expect(lastWrite(PENDING_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
    expect(signIn).toHaveBeenCalledWith(expect.objectContaining({ mobile: '07700900456', deviceId: DEVICE, inviteToken: INVITE, host: TENANTS.A.host }));
  });

  it('writes no session when the sign-in answers a session for another host than the one the code came to', async () => {
    signIn.mockResolvedValue({ registrationId: 'REG-SAMPLE-1', session: sessionFor(TENANTS.B, 'reporter') });
    const response = await POST(post({ phone: '07700900456', code: '123456' }, { [PENDING_COOKIE]: await withPending() }));
    expect(response.status).toBe(503);
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
    expect(JSON.stringify(await response.json())).not.toContain(TENANTS.B.id);
  });

  it('answers 410 expired when there is no pending code request, and does not call the back end', async () => {
    const response = await POST(post({ phone: '07700900456', code: '123456' }));
    expect(response.status).toBe(410);
    expect(await response.json()).toMatchObject({ code: 'expired' });
    expect(seenBackendIdentity).toHaveLength(0);
    expect(cookieWrites).toHaveLength(0);
  });

  it('answers 400 wrong-code for a wrong code, and writes no session', async () => {
    backendIdentity.verify = {
      status: 400,
      body: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'That code is not right' }] },
    };
    server.use(
      http.post(`${BACKEND_ROOT}/identity/code/verify`, (() =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'That code is not right' }] }, { status: 400 })) as HttpResponseResolver),
    );
    const response = await POST(post({ phone: '07700900456', code: '000000' }, { [PENDING_COOKIE]: await withPending() }));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ code: 'wrong-code' });
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
    expect(signIn).not.toHaveBeenCalled();
  });

  it('answers 410 expired when the back end says to ask for a new code (a lapsed code or five wrong tries)', async () => {
    server.use(
      http.post(`${BACKEND_ROOT}/identity/code/verify`, (() =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'Ask for a new code' }] }, { status: 400 })) as HttpResponseResolver),
    );
    const response = await POST(post({ phone: '07700900456', code: '000000' }, { [PENDING_COOKIE]: await withPending() }));
    expect(response.status).toBe(410);
    expect(await response.json()).toMatchObject({ code: 'expired' });
  });

  it('answers 503 not-built when the registration sign-in is not built yet, and writes no session', async () => {
    signIn.mockRejectedValueOnce(notBuilt('The registration sign-in'));
    const response = await POST(post({ phone: '07700900456', code: '123456' }, { [PENDING_COOKIE]: await withPending() }));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it('refuses a body that names a tenant or any field other than the number and the code', async () => {
    const response = await POST(post({ phone: '07700900456', code: '123456', tenantId: 'tenant-b' }, { [PENDING_COOKIE]: await withPending() }));
    expect(response.status).toBe(400);
    expect(seenBackendIdentity).toHaveLength(0);
  });

  it('refuses a code that is not six digits, without calling the back end', async () => {
    for (const code of ['12345', '1234567', 'abcdef', '']) {
      const response = await POST(post({ phone: '07700900456', code }, { [PENDING_COOKIE]: await withPending() }));
      expect(response.status).toBe(400);
    }
    expect(seenBackendIdentity).toHaveLength(0);
  });
});
