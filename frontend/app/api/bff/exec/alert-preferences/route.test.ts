// @vitest-environment node
import { csrfTokenFor } from '@/lib/auth/csrf';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { DEFAULT_ALERT_PREFERENCES } from '@/lib/exec/alertPrefs';
import { server } from '@/test/msw/server';
import {
  EXEC_BACKEND,
  execBackendHandlers,
  resetExecBackend,
  seenBackend,
  SUBSCRIBER_ID,
} from '@/test/msw/handlers/exec';
import { GET, PUT } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const URL_ = 'https://app.test/api/bff/exec/alert-preferences';
// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = await csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'user-1' }, 'N'.repeat(43));

function session(role: Role): Session {
  return { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: 'token-exec', expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

async function call(method: 'GET' | 'PUT', role: Role | null, payload?: unknown, withCsrf = true) {
  const cookies: Record<string, string> = { diucs_csrf: CSRF };
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const headers: Record<string, string> = {};
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  if (withCsrf && method === 'PUT') headers['X-CSRF-Token'] = CSRF;
  const request = requestWithCookies(URL_, cookies, {
    method,
    headers,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  return method === 'GET' ? GET(request) : PUT(request);
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetExecBackend();
  server.use(...execBackendHandlers);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/exec/alert-preferences', () => {
  it('answers the defaults for a practitioner who has never saved, in the BFF shape', async () => {
    const response = await call('GET', 'exec');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(DEFAULT_ALERT_PREFERENCES);
  });

  it('refuses a role that is not an executive or a shift lead, with no back-end call', async () => {
    const response = await call('GET', 'advisor');
    expect(response.status).toBe(403);
    expect(seenBackend).toHaveLength(0);
  });

  it('refuses a request with no session', async () => {
    expect((await call('GET', null)).status).toBe(401);
  });
});

describe('PUT /api/bff/exec/alert-preferences', () => {
  const valid = { ...DEFAULT_ALERT_PREFERENCES, deputy: SUBSCRIBER_ID, ackMinutes: 15 };

  it('rejects an acknowledgement window of 20 minutes with 400 and does not call the back end', async () => {
    const response = await call('PUT', 'exec', { ...valid, ackMinutes: 20 });
    expect(response.status).toBe(400);
    expect(seenBackend.filter((r) => r.method === 'PUT')).toHaveLength(0);
  });

  it('refuses an empty deputy with 400', async () => {
    expect((await call('PUT', 'exec', { ...valid, deputy: '' })).status).toBe(400);
  });

  it('refuses a request without the CSRF header', async () => {
    expect((await call('PUT', 'exec', valid, false)).status).toBe(403);
  });

  it('reads the current version, then writes with If-Match and an Idempotency-Key', async () => {
    const response = await call('PUT', 'exec', valid);
    expect(response.status).toBe(200);
    const put = seenBackend.find((r) => r.method === 'PUT');
    expect(put?.path).toBe(`/Subscription/${SUBSCRIBER_ID}`);
    expect(put?.ifMatch).toMatch(/^W\/"\d+"$/);
    expect(put?.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    expect(await response.json()).toEqual(expect.objectContaining({ ackMinutes: 15, deputy: SUBSCRIBER_ID }));
  });
});
