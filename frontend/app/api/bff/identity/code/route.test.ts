// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PENDING_COOKIE, readPending } from '@/lib/register/pending';
import { BACKEND_ROOT, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answerBackend, breakBackend, resetSeen, seen } from '@/test/applicant/backend';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { POST } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The registration code request (W23, DEC-900). No session and no number: the invitation says whose
// number the code goes to, and the back end sends it there. The browser's body never carries a
// number, a tenant or a person. The back end answers 202 for every open link, and the BFF keeps the
// invitation and a device id in a sealed cookie the browser cannot read.

const URL_ = `https://${TENANT_HOST}/api/bff/identity/code`;
const INVITE = 'InviteTokenSampleValue1';

function post(body: unknown) {
  return requestWithCookies(URL_, {}, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Host: TENANT_HOST },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeen();
});

describe('POST /api/bff/identity/code', () => {
  it('asks the back end for a code for the open invitation, with the request host and no number', async () => {
    answerBackend('post', '/identity/registration/code', 202, { accepted: true, resendAfterSeconds: 60 });
    const response = await POST(post({ purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ accepted: true, resendAfterSeconds: 60 });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ path: '/identity/registration/code', host: TENANT_HOST, body: { invitation: INVITE } });
  });

  it('keeps the invitation and a new device id in the sealed pending cookie, which holds no tenant', async () => {
    answerBackend('post', '/identity/registration/code', 202, { accepted: true, resendAfterSeconds: 60 });
    await POST(post({ purpose: 'registration', inviteToken: INVITE }));
    const written = lastWrite(PENDING_COOKIE);
    expect(written?.value).toBeTruthy();
    expect(written?.value).not.toContain(INVITE);
    expect(written?.value).not.toContain(TENANT_HOST);
    const pending = await readPending(requestWithCookies(URL_, { [PENDING_COOKIE]: written?.value ?? '' }));
    expect(pending?.inviteToken).toBe(INVITE);
    expect(pending?.deviceId).toMatch(/^[A-Za-z0-9_-]{22}$/);
  });

  it('keeps the device id of an earlier request, so a resend is for the same device', async () => {
    answerBackend('post', '/identity/registration/code', 202, { accepted: true, resendAfterSeconds: 60 });
    await POST(post({ purpose: 'registration', inviteToken: INVITE }));
    const first = await readPending(requestWithCookies(URL_, { [PENDING_COOKIE]: lastWrite(PENDING_COOKIE)?.value ?? '' }));
    await POST(
      requestWithCookies(URL_, { [PENDING_COOKIE]: lastWrite(PENDING_COOKIE)?.value ?? '' }, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Host: TENANT_HOST },
        body: JSON.stringify({ purpose: 'registration', inviteToken: INVITE }),
      }),
    );
    const second = await readPending(requestWithCookies(URL_, { [PENDING_COOKIE]: lastWrite(PENDING_COOKIE)?.value ?? '' }));
    expect(second?.deviceId).toBe(first?.deviceId);
  });

  it('refuses a body that names a number, a tenant, a person or any other field, and a bad link, without calling the back end', async () => {
    for (const body of [
      { purpose: 'registration', inviteToken: INVITE, phone: '07700900456' },
      { purpose: 'registration', inviteToken: INVITE, tenantId: 'other' },
      { purpose: 'registration', inviteToken: INVITE, person: 'x' },
      { purpose: 'other', inviteToken: INVITE },
      { purpose: 'registration', inviteToken: 'short' },
      { purpose: 'registration' },
    ]) {
      const response = await POST(post(body));
      expect(response.status).toBe(400);
    }
    expect(seen).toHaveLength(0);
    expect(cookieWrites).toHaveLength(0);
  });

  it('answers 404 for a link that is not open, and writes no pending cookie', async () => {
    answerBackend('post', '/identity/registration/code', 404, { resourceType: 'OperationOutcome', issue: [] });
    const response = await POST(post({ purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find an invitation for this link.' });
    expect(lastWrite(PENDING_COOKIE)).toBeUndefined();
  });

  it('passes the back end’s 429 on with its Retry-After, and writes no cookie', async () => {
    answerBackend('post', '/identity/registration/code', 429, { resourceType: 'OperationOutcome', issue: [] }, { 'Retry-After': '300' });
    const response = await POST(post({ purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(429);
    expect(response.headers.get('retry-after')).toBe('300');
    expect(lastWrite(PENDING_COOKIE)).toBeUndefined();
  });

  it('answers 503 with no detail when the back end cannot be reached', async () => {
    breakBackend('post', '/identity/registration/code');
    const response = await POST(post({ purpose: 'registration', inviteToken: INVITE }));
    expect(response.status).toBe(503);
    expect(await response.text()).not.toMatch(/fetch|ECONN/i);
  });
});
