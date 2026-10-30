// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'csrf-token-for-the-test-0123456789abcdefghij';
const URL_ = 'https://app.test/api/bff/lead/services/s-1/test-prompt';

function session(role: Role): Session {
  return { role, services: [], sub: 'user-1', backendToken: 'token-for-the-lead', expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

async function post(role: Role, csrf: boolean) {
  const cookies: Record<string, string> = { [SESSION_COOKIE]: await sealSession(session(role)) };
  const headers: Record<string, string> = { 'Idempotency-Key': 'test-prompt-key-0001' };
  if (csrf) {
    cookies[CSRF_COOKIE] = CSRF;
    headers[CSRF_HEADER] = CSRF;
  }
  return POST(requestWithCookies(URL_, cookies, { method: 'POST', headers }), { params: Promise.resolve({ id: 's-1' }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/lead/services/[id]/test-prompt', () => {
  it('answers 403 to an advisor', async () => {
    expect((await post('advisor', true)).status).toBe(403);
  });

  it('answers 403 without the CSRF header', async () => {
    expect((await post('lead', false)).status).toBe(403);
  });

  it('answers 501 for a lead until the back end has a route for a lead test prompt', async () => {
    const response = await post('lead', true);
    expect(response.status).toBe(501);
    expect(((await response.json()) as { code: string }).code).toBe('not-built');
  });
});
