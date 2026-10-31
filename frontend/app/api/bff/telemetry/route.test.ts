// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const URL_ = `https://${TENANTS.A.host}/api/bff/telemetry`;
// The back end counts the same batch into the tenant's aggregates (W9F), at its root.
const BACKEND_ROOT = 'http://backend.test';
const BACKEND_UI = `${BACKEND_ROOT}/telemetry/ui`;
// OTEL_HTTP_ENDPOINT is the collector's base. ui.* events are log records (DEC-331 item 5), so the
// batch goes to its OTLP logs receiver as OTLP/JSON (O04 mismatch, decided in DEC-740).
const COLLECTOR = 'https://collector.test';
const LOGS_RECEIVER = `${COLLECTOR}/v1/logs`;

function session(role: Role): Session {
  return sessionFor(TENANTS.A, role, { sub: 'user-1', backendToken: 'backend-token' });
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
let counted: Array<{ authorization: string | null; contentType: string | null; body: unknown }>;

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('OTEL_HTTP_ENDPOINT', COLLECTOR);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  forwarded = [];
  counted = [];
  server.use(
    http.post(BACKEND_UI, async ({ request }) => {
      counted.push({
        authorization: request.headers.get('authorization'),
        contentType: request.headers.get('content-type'),
        body: await request.json(),
      });
      return HttpResponse.json({ accepted: 1, dropped: 0 });
    }),
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

    await post(batch({ 'element.id': 'ADV-REF-INPUT', 'tenant.id': 'tenant-b' }));

    const [sent] = forwarded as Array<{
      resourceLogs: Array<{ scopeLogs: Array<{ logRecords: Array<{ attributes: Array<{ key: string; value: unknown }> }> }> }>;
    }>;
    const attributes = sent?.resourceLogs[0]?.scopeLogs[0]?.logRecords[0]?.attributes ?? [];
    expect(attributes).toContainEqual({ key: 'tenant.id', value: { stringValue: TENANTS.A.id } });
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

  describe('the back end counts the batch (W9F)', () => {
    it('sends the events that passed the allow-list to the back end with the session token, and no tenant', async () => {
      const response = await post({
        events: [
          {
            name: 'ui.click',
            at: 1_700_000_000_000,
            attributes: {
              'session.id': 'a1b2c3d4e5f60718',
              release: '0.1.0',
              'device.type': 'desktop',
              'element.id': 'ADV-OPT-REQUEST-BTN',
              'tenant.id': 'tenant-b',
              'field.value': 'DT4 8XX',
            },
          },
        ],
      });

      expect(response.status).toBe(204);
      expect(counted).toHaveLength(1);
      expect(counted[0]?.authorization).toBe('Bearer backend-token');
      expect(counted[0]?.contentType).toContain('json');
      expect(counted[0]?.body).toEqual({
        events: [
          {
            name: 'ui.click',
            attributes: {
              'session.id': 'a1b2c3d4e5f60718',
              release: '0.1.0',
              'device.type': 'desktop',
              'element.id': 'ADV-OPT-REQUEST-BTN',
            },
          },
        ],
      });
      expect(JSON.stringify(counted)).not.toContain('tenant');
      expect(JSON.stringify(counted)).not.toContain('DT4');
    });

    it('counts the batch even when no collector is set', async () => {
      vi.stubEnv('OTEL_HTTP_ENDPOINT', '');

      await post(batch({ 'element.id': 'ADV-REF-INPUT' }));

      expect(counted).toHaveLength(1);
      expect(forwarded).toEqual([]);
    });

    it('asks the back end for nothing when no event passed the allow-list', async () => {
      await post({ events: [{ name: 'patient.lookup', at: 1, attributes: {} }] });

      expect(counted).toEqual([]);
    });

    it('answers 204 whatever the back end does, and never says what it kept', async () => {
      server.use(http.post(BACKEND_UI, () => HttpResponse.json({ code: 'x' }, { status: 503 })));

      const response = await post(batch({ 'element.id': 'ADV-REF-INPUT' }));

      expect(response.status).toBe(204);
      expect(await response.text()).toBe('');
    });

    it('does not count a batch from another origin or with no session', async () => {
      await post(batch({ 'element.id': 'ADV-REF-INPUT' }), 'advisor', { origin: 'https://evil.test' });
      await post(batch({ 'element.id': 'ADV-REF-INPUT' }), null);

      expect(counted).toEqual([]);
    });
  });
});
