// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT, TENANT_HOST } from '@/test/fixtures/links';
import { requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { answerBackend, breakBackend, resetSeen, seen } from '@/test/applicant/backend';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { POST } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The invitation the registration page reads before it asks for a code (W23). The back end says
// whether the link is open, and for an open one the service and the last three digits of the number
// the code will go to. The browser never gets a tenant, a person or the whole number.

const URL_ = `https://${TENANT_HOST}/api/bff/identity/invitation`;
const INVITE = 'InviteTokenSampleValue1';
const EXPIRES = '2026-11-01T18:00:00Z';

function post(body: unknown, headers: Record<string, string> = { Host: TENANT_HOST }) {
  return requestWithCookies(URL_, {}, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetCookieWrites();
  resetSeen();
});

describe('POST /api/bff/identity/invitation', () => {
  it('reads the link in the request host’s tenant and answers the service and the end of the number', async () => {
    answerBackend('post', '/identity/invitation', 200, { state: 'open', serviceName: 'Community nursing', numberEnding: '456', expiresAt: EXPIRES });
    const response = await POST(post({ inviteToken: INVITE }));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toEqual({ state: 'open', serviceName: 'Community nursing', numberEnding: '456', expiresAt: EXPIRES });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ path: '/identity/invitation', host: TENANT_HOST, body: { invitation: INVITE } });
  });

  it('passes on an expired or used link as its state, with nothing else', async () => {
    answerBackend('post', '/identity/invitation', 200, { state: 'expired' });
    const response = await POST(post({ inviteToken: INVITE }));
    expect(await response.json()).toEqual({ state: 'expired' });
  });

  it('answers an unknown link as not found, with no detail', async () => {
    answerBackend('post', '/identity/invitation', 404, { resourceType: 'OperationOutcome', issue: [] });
    const response = await POST(post({ inviteToken: INVITE }));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find an invitation for this link.' });
  });

  it('refuses a body that names a tenant, a person or any other field, and a link of the wrong shape, without calling the back end', async () => {
    for (const body of [
      { inviteToken: INVITE, tenantId: 'other' },
      { inviteToken: INVITE, phone: '07700900456' },
      { inviteToken: 'short' },
      { inviteToken: 42 },
      '{not json',
    ]) {
      const response = await POST(post(body));
      expect(response.status).toBe(400);
    }
    expect(seen).toHaveLength(0);
  });

  it('answers 503 with no detail when the back end cannot be reached', async () => {
    breakBackend('post', '/identity/invitation');
    const response = await POST(post({ inviteToken: INVITE }));
    expect(response.status).toBe(503);
    const text = await response.text();
    expect(text).not.toMatch(/fetch|ECONN|backend/i);
  });
});
