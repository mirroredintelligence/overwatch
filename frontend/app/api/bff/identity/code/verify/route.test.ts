// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { PENDING_COOKIE, sealPending } from '@/lib/register/pending';
import { BACKEND_ROOT, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answerBackend, breakBackend, resetSeen, seen, unsignedToken } from '@/test/applicant/backend';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { TENANTS } from '@/test/tenants';
import { POST } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The registration code check (W23, DEC-900 to DEC-902). A right code ends in a reporter session the
// BFF seals. The tenant is the one the back end bound from the host (answered as `tenant`), the host
// is the request's, and the back end's token is kept in the sealed cookie only. Every negative case
// writes no session: a tenant or host the BFF cannot vouch for fails closed with a 503.

const URL_ = `https://${TENANT_HOST}/api/bff/identity/code/verify`;
const INVITE = 'InviteTokenSampleValue1';
const DEVICE = 'Dev1ceIdSampleValue_ab';
const SUB = 'person-sample-1';
// Whole seconds, as the back end writes an expiry (the session ends to the second).
const EXPIRES = new Date(Math.floor((Date.now() + 2 * 3600_000) / 1000) * 1000).toISOString();
const EXP_SECONDS = Math.floor(Date.parse(EXPIRES) / 1000);
const TOKEN = unsignedToken(SUB, EXP_SECONDS);
const TENANT = TENANTS.A.id;

function signedIn(overrides: Record<string, unknown> = {}) {
  return {
    token: TOKEN,
    expiresAt: EXPIRES,
    role: 'reporter',
    tenant: TENANT,
    registrationId: 'REG-SAMPLE-1',
    serviceId: 'SVC-SAMPLE-1',
    serviceName: 'Community nursing',
    ...overrides,
  };
}

async function withPending(): Promise<string> {
  return sealPending({ deviceId: DEVICE, inviteToken: INVITE });
}

async function post(body: unknown, cookies: Record<string, string> = {}) {
  return POST(
    requestWithCookies(URL_, { [PENDING_COOKIE]: cookies[PENDING_COOKIE] ?? (await withPending()), ...cookies }, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Host: TENANT_HOST },
      body: typeof body === 'string' ? body : JSON.stringify(body),
    }),
  );
}

async function sessionWritten() {
  const written = lastWrite(SESSION_COOKIE);
  return written?.value ? unsealSession(written.value) : null;
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeen();
});

describe('POST /api/bff/identity/code/verify: a right code', () => {
  it('signs in: checks the code with the invitation, the device and the host, and answers the registration id only', async () => {
    answerBackend('post', '/identity/registration/session', 200, signedIn());
    const response = await post({ code: '482913' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ registrationId: 'REG-SAMPLE-1' });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({
      path: '/identity/registration/session',
      host: TENANT_HOST,
      body: { invitation: INVITE, code: '482913', deviceId: DEVICE },
    });
  });

  it('seals a reporter session that carries the tenant and the host, and never a token in the answer', async () => {
    answerBackend('post', '/identity/registration/session', 200, signedIn());
    const response = await post({ code: '482913' });
    expect(JSON.stringify(await response.json())).not.toContain(TOKEN);
    const session = await sessionWritten();
    expect(session).toMatchObject({
      role: 'reporter',
      tenantId: TENANT,
      host: TENANT_HOST,
      sub: SUB,
      services: ['SVC-SAMPLE-1'],
      device: DEVICE,
      backendToken: TOKEN,
      expiresAt: EXPIRES,
    });
    expect(lastWrite(SESSION_COOKIE)?.options).toMatchObject({ httpOnly: true, sameSite: 'strict' });
  });

  it('clears the pending cookie once the session is written', async () => {
    answerBackend('post', '/identity/registration/session', 200, signedIn());
    await post({ code: '482913' });
    expect(lastWrite(PENDING_COOKIE)?.value ?? '').toBe('');
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(true);
  });
});

describe('POST /api/bff/identity/code/verify: a session the BFF cannot vouch for is refused, and no session is written', () => {
  it('answers 503 when the back end does not say which tenant it signed the applicant in for', async () => {
    const withoutTenant = signedIn();
    delete (withoutTenant as { tenant?: string }).tenant;
    answerBackend('post', '/identity/registration/session', 200, withoutTenant);
    const response = await post({ code: '482913' });
    expect(response.status).toBe(503);
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 503 when the tenant is not a tenant id', async () => {
    answerBackend('post', '/identity/registration/session', 200, signedIn({ tenant: 'Not A Tenant!' }));
    expect((await post({ code: '482913' })).status).toBe(503);
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 503 when the token is not one the BFF can read a person from', async () => {
    answerBackend('post', '/identity/registration/session', 200, signedIn({ token: 'not-a-token' }));
    expect((await post({ code: '482913' })).status).toBe(503);
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 503 when the expiry is not a future instant within twelve hours', async () => {
    // A token that lasts longer than the answer, so the answer's expiry is the one under test.
    const longToken = unsignedToken(SUB, Math.floor(Date.now() / 1000) + 2 * 86400);
    for (const expiresAt of [new Date(Date.now() - 60_000).toISOString(), new Date(Date.now() + 13 * 3600_000).toISOString(), 'soon']) {
      answerBackend('post', '/identity/registration/session', 200, signedIn({ expiresAt, token: longToken }));
      expect((await post({ code: '482913' })).status).toBe(503);
    }
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 503 when the request has no host, and writes no session', async () => {
    answerBackend('post', '/identity/registration/session', 200, signedIn());
    const response = await POST(
      requestWithCookies(URL_, { [PENDING_COOKIE]: await withPending() }, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Host: '' },
        body: JSON.stringify({ code: '482913' }),
      }),
    );
    expect(response.status).toBe(503);
    expect(await sessionWritten()).toBeNull();
  });
});

describe('POST /api/bff/identity/code/verify: the answers the back end gives for a code that is not right', () => {
  it('answers 400 wrong-code for a wrong code, and writes no session or pending clear', async () => {
    answerBackend('post', '/identity/registration/session', 400, {
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'invalid', diagnostics: 'That code is not right' }],
    });
    const response = await post({ code: '000000' });
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: 'wrong-code', message: 'That code is not right. Check it and try again.' });
    expect(await sessionWritten()).toBeNull();
    expect(lastWrite(PENDING_COOKIE)).toBeUndefined();
  });

  it('answers 410 expired when the back end says to ask for a new code (a lapsed code or five wrong tries)', async () => {
    answerBackend('post', '/identity/registration/session', 400, {
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'invalid', diagnostics: 'Ask for a new code' }],
    });
    const response = await post({ code: '000000' });
    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ code: 'expired', message: 'That code has expired. Ask for a new code.' });
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 403 no-invitation when the back end does not know the link (404)', async () => {
    answerBackend('post', '/identity/registration/session', 404, { resourceType: 'OperationOutcome', issue: [] });
    const response = await post({ code: '482913' });
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ code: 'no-invitation' });
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 409 device-refused when the code is right but this phone cannot be set up with it', async () => {
    answerBackend('post', '/identity/registration/session', 409, { resourceType: 'OperationOutcome', issue: [] });
    const response = await post({ code: '482913' });
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ code: 'device-refused' });
    expect(await sessionWritten()).toBeNull();
  });

  it('answers 429 throttled when the back end refuses more tries', async () => {
    answerBackend('post', '/identity/registration/session', 429, { resourceType: 'OperationOutcome', issue: [] });
    const response = await post({ code: '482913' });
    expect(response.status).toBe(429);
    expect(await response.json()).toMatchObject({ code: 'throttled' });
  });

  it('answers 410 expired, and calls nothing, when there is no pending request for this phone', async () => {
    const response = await POST(
      requestWithCookies(URL_, {}, { method: 'POST', headers: { 'Content-Type': 'application/json', Host: TENANT_HOST }, body: JSON.stringify({ code: '482913' }) }),
    );
    expect(response.status).toBe(410);
    expect(seen).toHaveLength(0);
  });

  it('answers 503 with no detail when the back end cannot be reached, and writes no session', async () => {
    breakBackend('post', '/identity/registration/session');
    const response = await post({ code: '482913' });
    expect(response.status).toBe(503);
    expect(await response.text()).not.toMatch(/fetch|ECONN/i);
    expect(await sessionWritten()).toBeNull();
  });
});

describe('POST /api/bff/identity/code/verify: the body', () => {
  it('refuses a body that names a number, a tenant, an invitation or any field but the code, without calling the back end', async () => {
    for (const body of [
      { code: '482913', phone: '07700900456' },
      { code: '482913', tenantId: 'other' },
      { code: '482913', inviteToken: 'OtherInviteToken123456' },
      { code: '482913', mobile: '07700900456' },
    ]) {
      expect((await post(body)).status).toBe(400);
    }
    expect(seen).toHaveLength(0);
  });

  it('refuses a code that is not six digits, without calling the back end', async () => {
    for (const code of ['12345', '1234567', 'abcdef', '']) {
      expect((await post({ code })).status).toBe(400);
    }
    expect(seen).toHaveLength(0);
  });
});
