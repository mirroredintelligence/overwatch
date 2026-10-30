// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sessionFromRequest, SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The session seals a fixed set of claims and carries no tenant yet. The tenant test below supplies
// one through this spy, so the route's own rule (the tenant comes from the session) is still tested.
vi.mock('@/lib/auth/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/auth/session')>();
  return { ...actual, sessionFromRequest: vi.fn(actual.sessionFromRequest) };
});

const URL_ = 'https://app.test/api/bff/telemetry';
// OTEL_HTTP_ENDPOINT is the collector's base. ui.* events are log records (DEC-331 item 5), so the
// batch goes to its OTLP logs receiver as OTLP/JSON (O04 mismatch, decided in DEC-740).
const COLLECTOR = 'https://collector.test';
const LOGS_RECEIVER = `${COLLECTOR}/v1/logs`;

function session(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'user-1',
    backendToken: 'backend-token',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(body: unknown, role: Role | null = 'advisor', options: { origin?: string } = {}) {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const headers: Record<string, string> = { 'Content-Type': 'text/plain;charset=UTF-8' };
  if (options.origin !== undefined) headers.Origin = options.origin;
  return POST(
    requestWithCookies(URL_, cookies, {
      method: 'POST',
      headers,
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
    http.post(LOGS_RECEIVER, async ({ request }) => {
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

  it('sends the batch to the logs receiver as OTLP/JSON, one log record per event, with the event name as its body', async () => {
    await post(batch({ 'element.id': 'ADV-OPT-REQUEST-BTN', dwell_ms: 812, valid: true }));

    const body = forwarded[0] as {
      resourceLogs: { scopeLogs: { logRecords: { body: { stringValue: string }; attributes: { key: string; value: Record<string, unknown> }[] }[] }[] }[];
    };
    const record = body.resourceLogs[0]?.scopeLogs[0]?.logRecords[0];
    expect(record?.body).toEqual({ stringValue: 'ui.chip' });
    expect(record?.attributes).toContainEqual({ key: 'element.id', value: { stringValue: 'ADV-OPT-REQUEST-BTN' } });
    expect(record?.attributes).toContainEqual({ key: 'dwell_ms', value: { doubleValue: 812 } });
    expect(record?.attributes).toContainEqual({ key: 'valid', value: { boolValue: true } });
  });

  it('drops an attribute it does not know, such as field.value', async () => {
    await post(batch({ 'element.id': 'ADV-REF-INPUT', 'field.value': 'DT4 8XX' }));

    expect(JSON.stringify(forwarded)).not.toContain('field.value');
    expect(JSON.stringify(forwarded)).not.toContain('DT4');
  });

  it('takes the tenant from the session, never from the browser', async () => {
    vi.mocked(sessionFromRequest).mockResolvedValueOnce({ ...session('advisor'), tenantId: 'tenant-a' } as Session);

    await post(batch({ 'element.id': 'ADV-REF-INPUT', 'tenant.id': 'tenant-b' }));

    const [sent] = forwarded as Array<{ events: Array<{ attributes: Record<string, unknown> }> }>;
    expect(sent?.events[0]?.attributes['tenant.id']).toBe('tenant-a');
    expect(JSON.stringify(forwarded)).not.toContain('tenant-b');
  });

  it('refuses a batch sent from another origin', async () => {
    const response = await post(batch({ 'element.id': 'ADV-REF-INPUT' }), 'advisor', {
      origin: 'https://evil.test',
    });

    expect(response.status).toBe(403);
    expect(forwarded).toEqual([]);
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
