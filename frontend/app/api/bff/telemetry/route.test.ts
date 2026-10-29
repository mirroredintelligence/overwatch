// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const URL_ = 'https://app.test/api/bff/telemetry';
const COLLECTOR = 'https://collector.test/v1/events';

function session(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'user-1',
    backendToken: 'backend-token',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(body: unknown, role: Role | null = 'advisor') {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return POST(
    requestWithCookies(URL_, cookies, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: typeof body === 'string' ? body : JSON.stringify(body),
    }),
  );
}

const batch = (attributes: Record<string, unknown>) => ({
  events: [{ name: 'ui.chip', at: 1_700_000_000_000, attributes }],
});

let forwarded: unknown[];

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('OTEL_HTTP_ENDPOINT', COLLECTOR);
  forwarded = [];
  server.use(
    http.post(COLLECTOR, async ({ request }) => {
      forwarded.push(await request.json());
      return new HttpResponse(null, { status: 202 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/telemetry', () => {
  it('answers 204 and forwards the allowed attributes of a batch', async () => {
    const response = await post(
      batch({ 'element.id': 'ADV-OPT-REQUEST-BTN', state: 'on', 'page.route': '/case/[ref]' }),
    );

    expect(response.status).toBe(204);
    expect(JSON.stringify(forwarded)).toContain('ADV-OPT-REQUEST-BTN');
  });

  it('drops an attribute it does not know, such as field.value', async () => {
    await post(batch({ 'element.id': 'ADV-REF-INPUT', 'field.value': 'DT4 8XX' }));

    expect(JSON.stringify(forwarded)).not.toContain('field.value');
    expect(JSON.stringify(forwarded)).not.toContain('DT4');
  });

  it('takes a tenant only from the session, never from the browser', async () => {
    await post(batch({ 'element.id': 'ADV-REF-INPUT', 'tenant.id': 'tenant-b' }));

    expect(JSON.stringify(forwarded)).not.toContain('tenant-b');
  });

  it('refuses an event name that is not one of the ui events in scope', async () => {
    await post({ events: [{ name: 'patient.lookup', at: 1, attributes: {} }] });

    expect(forwarded).toEqual([]);
  });

  it('answers 401 with no session', async () => {
    const response = await post(batch({ 'element.id': 'ADV-REF-INPUT' }), null);

    expect(response.status).toBe(401);
  });

  it('answers 400 to a body that is not JSON', async () => {
    const response = await post('not json');

    expect(response.status).toBe(400);
  });

  it('discards the batch when no endpoint is configured, and still answers 204', async () => {
    vi.stubEnv('OTEL_HTTP_ENDPOINT', '');

    const response = await post(batch({ 'element.id': 'ADV-REF-INPUT' }));

    expect(response.status).toBe(204);
    expect(forwarded).toEqual([]);
  });
});
