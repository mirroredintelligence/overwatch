// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { readAll, streamOf } from '@/test/sse';
import { server } from '@/test/msw/server';

// The visitor address of the request in progress reaches the back end as CF-Connecting-IP, from the
// pre-session calls (`callBackend`) and from the token calls (`fhirFetch`), with the origin secret (KI-1303).
const request = vi.hoisted(() => ({ headers: null as Headers | null }));
vi.mock('next/headers', () => ({
  headers: async () => {
    if (request.headers === null) throw new Error('outside a request');
    return request.headers;
  },
}));

import { fhirFetch, fhirStream } from './client';
import { callBackend } from './hostCall';

const SECRET = 'edge-secret-value-of-sufficient-length-0123456789';
const PING = `${BACKEND_ROOT}/public/ping`;
const FHIR = `${BACKEND_ROOT}/fhir`;

function spy(url: string) {
  const seen: Record<string, string | null>[] = [];
  server.use(
    http.get(url, ({ request: r }) => {
      seen.push({
        ip: r.headers.get('cf-connecting-ip'),
        auth: r.headers.get('x-edge-auth'),
        forwarded: r.headers.get('x-forwarded-host'),
        xff: r.headers.get('x-forwarded-for'),
      });
      return HttpResponse.json({});
    }),
  );
  return seen;
}

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', FHIR);
  request.headers = new Headers({ 'x-forwarded-for': '198.51.100.1, 203.0.113.9', 'cf-connecting-ip': '192.0.2.200' });
});

afterEach(() => {
  request.headers = null;
  vi.unstubAllEnvs();
});

describe('callBackend with the request in progress', () => {
  beforeEach(() => vi.stubEnv('OVERWATCH_EDGE_ORIGIN_SECRET', SECRET));

  it('sends the right-most x-forwarded-for entry, not a client-supplied cf-connecting-ip', async () => {
    const seen = spy(PING);
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    expect(seen).toEqual([{ ip: '203.0.113.9', auth: SECRET, forwarded: 'a.test', xff: null }]);
  });

  it('sends cf-connecting-ip when the deployment is set to trust it', async () => {
    vi.stubEnv('OVERWATCH_VISITOR_ADDRESS_SOURCE', 'cf-connecting-ip');
    const seen = spy(PING);
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    expect(seen[0]?.ip).toBe('192.0.2.200');
  });

  it('sends none when the header is not one address, and an explicit address or null wins', async () => {
    const seen = spy(PING);
    request.headers = new Headers({ 'x-forwarded-for': '203.0.113.9, junk' });
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    request.headers = new Headers({ 'x-forwarded-for': '203.0.113.9' });
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test', clientIp: null });
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test', clientIp: '198.51.100.7' });
    expect(seen.map((s) => s.ip)).toEqual([null, null, '198.51.100.7']);
  });
});

describe('fhirFetch and fhirStream', () => {
  it('send the origin secret and the visitor, and no X-Forwarded-Host, when there is a secret', async () => {
    vi.stubEnv('OVERWATCH_EDGE_ORIGIN_SECRET', SECRET);
    const seen = spy(`${FHIR}/Patient/1`);
    await fhirFetch('/Patient/1', { token: 'token-for-tests' });
    expect(seen).toEqual([{ ip: '203.0.113.9', auth: SECRET, forwarded: null, xff: null }]);

    server.use(
      http.get(`${FHIR}/stream`, ({ request: r }) => {
        seen.push({ ip: r.headers.get('cf-connecting-ip'), auth: r.headers.get('x-edge-auth'), forwarded: null, xff: null });
        return new HttpResponse(streamOf(['data: x\n\n']), { headers: { 'Content-Type': 'text/event-stream' } });
      }),
    );
    const { body } = await fhirStream('/stream', { token: 'token-for-tests' });
    await readAll(body);
    expect(seen[1]).toMatchObject({ ip: '203.0.113.9', auth: SECRET });
  });

  it('send no edge header without a secret, or outside a request', async () => {
    const seen = spy(`${FHIR}/Patient/1`);
    await fhirFetch('/Patient/1', { token: 'token-for-tests' });
    vi.stubEnv('OVERWATCH_EDGE_ORIGIN_SECRET', SECRET);
    request.headers = null;
    await fhirFetch('/Patient/1', { token: 'token-for-tests' });
    expect(seen).toEqual([
      { ip: null, auth: null, forwarded: null, xff: null },
      { ip: null, auth: null, forwarded: null, xff: null },
    ]);
  });
});
