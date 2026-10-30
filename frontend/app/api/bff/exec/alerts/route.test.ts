// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND, execBackendHandlers, resetExecBackend, seenBackend } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

function session(role: Role): Session {
  return { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

async function get(role: Role | null, query = '?state=open') {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`https://app.test/api/bff/exec/alerts${query}`, cookies));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetExecBackend();
  server.use(...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/exec/alerts', () => {
  it('lists the caller\'s open alerts with the service name from the board and the count', async () => {
    const response = await get('exec');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      counts: { open: 1 },
      items: [
        {
          id: 'al-1',
          kind: 'not-updated',
          serviceId: 'svc-ucr-west',
          serviceName: 'UCR West',
          detail: null,
          raisedAt: '2026-10-23T13:04:00Z',
          state: 'new',
          escalatesAt: '2026-10-23T13:19:00Z',
          escalatesTo: 'deputy',
        },
      ],
    });
    expect(seenBackend[0]?.path).toBe('/Task?code=acknowledge-alert&owner=me');
  });

  it('answers unavailable for the acknowledged and closed tabs, which the back end does not list', async () => {
    const response = await get('exec', '?state=acknowledged');
    expect(response.status).toBe(503);
    expect(seenBackend).toHaveLength(0);
  });

  it('refuses a state it does not know with 400', async () => {
    expect((await get('exec', '?state=everything')).status).toBe(400);
  });

  it('refuses a role that is not an executive or a shift lead', async () => {
    expect((await get('advisor')).status).toBe(403);
  });
});
