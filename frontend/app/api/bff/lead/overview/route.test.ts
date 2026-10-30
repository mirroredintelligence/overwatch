// @vitest-environment node
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { GET } from './route';
import { TENANTS } from '@/test/tenants';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const URL_ = `https://${TENANTS.A.host}/api/bff/lead/overview`;

function session(role: Role): Session {
  return {
    role,
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: 'user-1',
    backendToken: 'token-for-the-lead',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(role: Role | null) {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(URL_, cookies));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/lead/overview', () => {
  it('answers 403 to an advisor, who may not see the lead page', async () => {
    const response = await get('advisor');
    expect(response.status).toBe(403);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
  });

  it('answers 401 with no session', async () => {
    expect((await get(null)).status).toBe(401);
  });

  it('answers 501 for a lead until the back end has a read for the overview, and never an empty overview', async () => {
    const response = await get('lead');
    expect(response.status).toBe(501);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.code).toBe('not-built');
    expect(body).not.toHaveProperty('chasing');
  });
});
