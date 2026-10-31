// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE, TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { frame, readAll, streamOf } from '@/test/sse';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

// GET /api/bff/wall/network-events (TEN-072): the back end's `GET /screens/me/network-events`, relayed for a
// wall screen. The screen names no network: its record does. Only `network-board` (the time of a change)
// and `scope-ended` (the screen may no longer read it) are forwarded, cut down to that.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const CHANGED = '{"changedAt":"2026-10-23T13:12:00+00:00"}';
const upstream: Request[] = [];

function backend(chunks: string[], options: { hold?: boolean; onClosed?: () => void; status?: number } = {}) {
  server.use(
    http.get(`${ROOT}/screens/me/network-events`, ({ request }) => {
      upstream.push(request.clone());
      request.signal.addEventListener('abort', () => options.onClosed?.());
      if (options.status !== undefined) return HttpResponse.json({}, { status: options.status });
      return new HttpResponse(streamOf(chunks, { hold: options.hold }), { headers: { 'Content-Type': 'text/event-stream' } });
    }),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  upstream.length = 0;
});
afterEach(() => vi.unstubAllEnvs());

const ask = (role: Parameters<typeof requestAs>[1], path = '/api/bff/wall/network-events', headers: Record<string, string> = {}) =>
  requestAs(TENANTS.A, role, { path, headers, session: { sub: 'screen-1', backendToken: TOKEN_ORG_A } });

describe('GET /api/bff/wall/network-events', () => {
  it('relays network-board events and scope-ended, with the screen’s own token and no network named', async () => {
    backend([frame('network-board', CHANGED), frame('scope-ended', '{}')]);
    const response = await GET(await ask('wall'));
    expect(response.status).toBe(200);
    expect(await readAll(response.body as ReadableStream<Uint8Array>)).toBe(`event: network-board\ndata: ${CHANGED}\n\nevent: scope-ended\ndata: {}\n\n`);
    expect(upstream).toHaveLength(1);
    expect(upstream[0]?.headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect(new URL(upstream[0]!.url).search).toBe('');
  });

  it('drops the tenant board’s events on this stream', async () => {
    backend([frame('board', '{"serviceId":"svc-1"}'), frame('booking.updated', '{"serviceId":"svc-1"}')]);
    expect(await readAll((await GET(await ask('wall'))).body as ReadableStream<Uint8Array>)).toBe('');
  });

  it('answers as an event stream no cache may store or transform', async () => {
    backend([frame('network-board', CHANGED)]);
    const response = await GET(await ask('wall'));
    expect(response.headers.get('content-type')).toBe('text/event-stream; charset=utf-8');
    expect(response.headers.get('cache-control')).toContain('no-store');
    await response.body?.cancel();
  });

  it('closes the back end connection when the browser goes away', async () => {
    let closed = false;
    backend([frame('network-board', CHANGED)], { hold: true, onClosed: () => (closed = true) });
    const controller = new AbortController();
    const request = await ask('wall');
    const response = await GET(new Request(request, { signal: controller.signal }));
    controller.abort();
    await response.body?.cancel().catch(() => undefined);
    await vi.waitFor(() => expect(closed).toBe(true));
  });

  it('is for a wall screen only: 401 with no session and 403 for every person’s role, with the back end not asked', async () => {
    backend([]);
    expect((await GET(new Request(`https://${TENANTS.A.host}/api/bff/wall/network-events`, { headers: { Host: TENANTS.A.host } }))).status).toBe(401);
    for (const role of ['advisor', 'clinical', 'lead', 'owner', 'exec', 'reporter', 'support', 'audit'] as const) expect((await GET(await ask(role))).status, role).toBe(403);
    expect(upstream).toHaveLength(0);
  });

  it('passes the back end’s refusal on (404 for a screen not set to a network), and keeps 401', async () => {
    backend([], { status: 404 });
    expect((await GET(await ask('wall'))).status).toBe(404);
    backend([], { status: 401 });
    expect((await GET(await ask('wall'))).status).toBe(401);
  });

  it('refuses a request that names a tenant, a scope or a network', async () => {
    backend([]);
    for (const path of ['/api/bff/wall/network-events?tenant=x', '/api/bff/wall/network-events?networkId=net-sample', '/api/bff/wall/network-events?scope=network']) {
      expect((await GET(await ask('wall', path))).status, path).toBe(400);
    }
    expect(upstream).toHaveLength(0);
  });
});
