// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { callBackend } from '@/lib/fhir/hostCall';
import { fhirFetch } from '@/lib/fhir/client';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { ACCEPTED_BODY_TYPES, BODY_METHODS, EXEMPT_PATH_PREFIXES, backendEdge, edgeRefusal } from '@/test/backend-edge';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';

// The back end's body-type rule as the tests model it (test/backend-edge.ts). A BFF route that POSTed with
// no body and no Content-Type answered 415 on a real stack and passed every test, because the stand-in
// answered whatever it was sent. These tests show the model refuses what the back end refuses, that it
// matches the back end's source, and that the calls that used to slip through now carry the type.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const BACKEND = 'http://backend.test';
const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const call = (method: string, path: string, headers: Record<string, string> = {}) =>
  edgeRefusal({ method, url: `${BACKEND}${path}`, headers: new Headers(headers) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => {
  vi.unstubAllEnvs();
  backendEdge.reset();
});

describe('the model of BodyTypeMiddleware', () => {
  it('refuses a POST with no Content-Type, with or without a body', () => {
    expect(call('POST', '/lead/services/s1/remind')).toEqual({ status: 415, method: 'POST', url: '/lead/services/s1/remind' });
  });

  it('refuses a PUT with no Content-Type, and a body of another type', () => {
    expect(call('PUT', '/fhir/Task/1')).not.toBeNull();
    expect(call('POST', '/fhir/Task', { 'Content-Type': 'text/plain' })).not.toBeNull();
    expect(call('POST', '/fhir/Task', { 'Content-Type': 'application/x-www-form-urlencoded' })).not.toBeNull();
  });

  it.each(['application/json', 'application/fhir+json', 'application/fhir+json; fhirVersion=4.3', 'Application/JSON; charset=utf-8'])(
    'lets %s through',
    (type) => expect(call('POST', '/fhir/Task', { 'Content-Type': type })).toBeNull(),
  );

  it('says nothing about a GET, a DELETE or a PATCH', () => {
    for (const method of ['GET', 'HEAD', 'DELETE', 'PATCH']) expect(call(method, '/fhir/Task/1')).toBeNull();
  });

  it('leaves the link pages and the webhooks to their own rules', () => {
    expect(call('POST', '/links/abc/renew')).toBeNull();
    expect(call('POST', '/webhooks/twilio/sms')).toBeNull();
  });

  it('does not judge a call to another origin', () => {
    expect(edgeRefusal({ method: 'POST', url: 'https://login.entra-fake.test/token', headers: new Headers() })).toBeNull();
  });

  it('matches the back end source: the same types, methods and exempt prefixes', () => {
    const source = readFileSync(
      fileURLToPath(new URL('../../backend/src/diucs/adapters/inbound/fhir_rest/errors.py', import.meta.url)),
      'utf8',
    );
    const set = (name: string) => [...source.match(new RegExp(`${name}\\s*=\\s*frozenset\\(\\{([^}]*)\\}\\)`))![1]!.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(set('ACCEPTED_BODY_TYPES').sort()).toEqual([...ACCEPTED_BODY_TYPES].sort());
    expect(set('_BODY_METHODS').sort()).toEqual([...BODY_METHODS].sort());
    const prefix = (name: string) => new RegExp(`${name}\\s*=\\s*"([^"]+)"`).exec(source)![1]!;
    expect([prefix('WEBHOOK_PATH_PREFIX'), prefix('LINK_PATH_PREFIX')].sort()).toEqual([...EXEMPT_PATH_PREFIXES].sort());
  });
});

describe('the installed model', () => {
  it('fails the test of a call the real back end would refuse', async () => {
    server.use(http.post(`${BACKEND}/fhir/Probe`, () => HttpResponse.json({})));
    await fetch(`${BACKEND}/fhir/Probe`, { method: 'POST', headers: { Authorization: 'Bearer token-for-the-lead' } });
    expect(backendEdge.refusals()).toHaveLength(1);
    expect(() => backendEdge.assertClean()).toThrow(/415: POST \/fhir\/Probe/);
    backendEdge.reset();
    expect(() => backendEdge.assertClean()).not.toThrow();
  });
});

describe('a call with no body still carries the body type (the class of bug)', () => {
  it('fhirFetch POST with no body sends application/fhir+json', async () => {
    let type: string | null = 'unset';
    server.use(http.post(`${ROOT}/lead/services/s1/remind`, ({ request }) => { type = request.headers.get('content-type'); return HttpResponse.json({}); }));
    await fhirFetch('/lead/services/s1/remind', { method: 'POST', root: true, token: 'token-for-the-lead' });
    expect(type).toMatch(/^application\/fhir\+json/);
    expect(backendEdge.refusals()).toEqual([]);
  });

  it('fhirFetch PUT with no body sends it too', async () => {
    server.use(http.put(`${ROOT}/fhir/Probe/1`, () => HttpResponse.json({})));
    await fhirFetch('/Probe/1', { method: 'PUT', token: 'token-for-the-lead' });
    expect(backendEdge.refusals()).toEqual([]);
  });

  it('fhirFetch GET sends none', async () => {
    let type: string | null = 'unset';
    server.use(http.get(`${ROOT}/fhir/Probe/2`, ({ request }) => { type = request.headers.get('content-type'); return HttpResponse.json({}); }));
    await fhirFetch('/Probe/2', { token: 'token-for-the-lead' });
    expect(type).toBeNull();
  });

  it('callBackend POST with no body sends application/json', async () => {
    server.use(http.post(`${ROOT}/identity/status`, () => HttpResponse.json({})));
    await callBackend({ method: 'POST', path: '/identity/status', host: TENANTS.A.host });
    expect(backendEdge.refusals()).toEqual([]);
  });
});

describe('the lead routes that post with no body', () => {
  const lead = (path: string) => leadRequest(`https://app.test${path}`, 'lead', { method: 'POST', csrf: true, key: 'edge-key-0001' });
  const ctx = { params: Promise.resolve({ id: 'x-1' }) };

  it('remind', async () => {
    const { POST } = await import('@/app/api/bff/lead/services/[id]/remind/route');
    server.use(http.post(`${ROOT}/lead/services/x-1/remind`, () => HttpResponse.json({ reminded: true })));
    expect((await POST(await lead('/api/bff/lead/services/x-1/remind'), ctx)).status).toBe(200);
    expect(backendEdge.refusals()).toEqual([]);
  });

  it('test-prompt with no channel', async () => {
    const { POST } = await import('@/app/api/bff/lead/services/[id]/test-prompt/route');
    server.use(http.post(`${ROOT}/lead/services/x-1/test-prompt`, () => HttpResponse.json({ channel: 'text', numberEnding: '4821' })));
    expect((await POST(await lead('/api/bff/lead/services/x-1/test-prompt'), ctx)).status).toBe(200);
    expect(backendEdge.refusals()).toEqual([]);
  });

  it('invitation resend', async () => {
    const { POST } = await import('@/app/api/bff/lead/invitations/[id]/resend/route');
    server.use(http.post(`${ROOT}/lead/invitations/x-1/resend`, () => HttpResponse.json({ invitationId: 'x-1', registrationId: 'r-1', expiresAt: '2026-10-31T10:00:00Z' })));
    expect((await POST(await lead('/api/bff/lead/invitations/x-1/resend'), ctx)).status).toBe(200);
    expect(backendEdge.refusals()).toEqual([]);
  });

  it('invitation switch-to-text', async () => {
    const { POST } = await import('@/app/api/bff/lead/invitations/[id]/switch-to-text/route');
    server.use(http.post(`${ROOT}/lead/invitations/x-1/switch-to-text`, () => HttpResponse.json({ channel: 'text' })));
    expect((await POST(await lead('/api/bff/lead/invitations/x-1/switch-to-text'), ctx)).status).toBe(200);
    expect(backendEdge.refusals()).toEqual([]);
  });
});
