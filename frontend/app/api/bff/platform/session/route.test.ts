// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OPERATOR_COOKIE } from '@/lib/operator/session';
import { cookieWrites, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { OPERATOR_ACCOUNT, requestAsOperator } from '@/test/operator';
import { server } from '@/test/msw/server';
import { DELETE, GET } from './route';

// The console's view of its own session (TEN-083, DEC-1005): the role, the permissions and the time it
// ends, from `GET /platform/session`, and the CSRF token the console sends. Never the back-end token.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const OPERATOR = { role: 'platform-operator', accountRef: OPERATOR_ACCOUNT, expiresAt: '2026-10-30T10:00:00Z', permissions: ['tenants:list', 'tenants:read', 'tenants:provision', 'tenants:lifecycle', 'audit:read'] };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
});
afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/platform/session', () => {
  it('answers the role, the permissions, the end and a CSRF token, and sets the CSRF cookie', async () => {
    server.use(http.get(`${ROOT}/platform/session`, ({ request }) => {
      expect(request.headers.get('authorization')).toMatch(/^Bearer /);
      return HttpResponse.json(OPERATOR);
    }));
    const response = await GET(await requestAsOperator('platform-operator'));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ role: 'platform-operator', expiresAt: '2026-10-30T10:00:00Z', permissions: OPERATOR.permissions });
    expect(typeof body.csrfToken).toBe('string');
    expect(cookieWrites.find((w) => w.name === 'diucs_op_csrf')?.value).toBe(body.csrfToken);
  });

  it('never carries the back-end token, a tenant or the sealed session', async () => {
    server.use(http.get(`${ROOT}/platform/session`, () => HttpResponse.json({ ...OPERATOR, token: 'leak', tenant: 'trust-a' })));
    const request = await requestAsOperator('platform-operator');
    const response = await GET(request);
    const text = await response.text();
    expect(text).not.toMatch(/leak|trust-a|operator-token|test-signature/);
    expect(Object.keys(JSON.parse(text)).sort()).toEqual(['accountRef', 'csrfToken', 'expiresAt', 'permissions', 'role']);
  });

  it('answers 401 with no session and 503 when the back end cannot be read (never an empty session)', async () => {
    expect((await GET(await new Request('https://console.example.test/x', { headers: { Host: 'console.example.test' } }))).status).toBe(401);
    server.use(http.get(`${ROOT}/platform/session`, () => HttpResponse.json({}, { status: 503 })));
    const response = await GET(await requestAsOperator('support'));
    expect(response.status).toBe(503);
    expect(await response.json()).not.toHaveProperty('role');
  });

  it('is a failed read, not a session, when the back end answers a shape that is not one', async () => {
    server.use(http.get(`${ROOT}/platform/session`, () => HttpResponse.json({ role: 'lead', permissions: [] })));
    expect((await GET(await requestAsOperator('platform-operator'))).status).toBeGreaterThanOrEqual(500);
  });
});

describe('DELETE /api/bff/platform/session', () => {
  it('ends the session, clears both cookies and the browser’s stored data, and needs the CSRF token', async () => {
    expect((await DELETE(await requestAsOperator('platform-operator', { method: 'DELETE' }))).status).toBe(403);
    resetCookieWrites();
    const response = await DELETE(await requestAsOperator('platform-operator', { method: 'DELETE', csrf: true }));
    expect(response.status).toBe(204);
    expect(response.headers.get('clear-site-data')).toBe('"cache", "storage"');
    const cleared = cookieWrites.filter((w) => w.value === '').map((w) => w.name).sort();
    expect(cleared).toEqual([OPERATOR_COOKIE, 'diucs_op_csrf'].sort());
  });
});
