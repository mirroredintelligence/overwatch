// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES, type Role } from '@/lib/auth/session';
import { NETWORK_ID, networkRequest } from '@/test/network';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { NETWORK_ROOT, networkHandlers, resetNetworkBackend, seenNetwork } from '@/test/msw/handlers/network';
import { server } from '@/test/msw/server';
import { frame, readAll, streamOf } from '@/test/sse';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

// TEN-068: the network stream relay. The availability is checked before the stream is opened, the
// network's own channel is relayed (the time of a change, and "scope ended"), and the tenant board's
// events never cross.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const EVENTS = `${NETWORK_ROOT}/network/${NETWORK_ID}/events`;
const CHANGED = '{"changedAt":"2026-10-23T13:12:00+00:00"}';
const upstream: Request[] = [];

function backend(chunks: string[], options: { hold?: boolean; onClosed?: () => void } = {}) {
  server.use(
    http.get(EVENTS, ({ request }) => {
      upstream.push(request.clone());
      request.signal.addEventListener('abort', () => options.onClosed?.());
      return new HttpResponse(streamOf(chunks, { hold: options.hold }), { headers: { 'Content-Type': 'text/event-stream' } });
    }),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${NETWORK_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetNetworkBackend();
  upstream.length = 0;
  server.use(...networkHandlers);
});
afterEach(() => vi.unstubAllEnvs());

const get = async (role: Role, tenant = TENANTS.A, query: Record<string, string> | string = { networkId: NETWORK_ID }) =>
  GET(await networkRequest(tenant, role, '/events', query));

describe('GET /api/bff/network/events', () => {
  it('relays network-board events and scope-ended, from the network’s own channel, and checks availability first', async () => {
    backend([frame('network-board', CHANGED), frame('scope-ended', '{}')]);
    const response = await get('advisor');
    expect(response.status).toBe(200);
    expect(await readAll(response.body as ReadableStream<Uint8Array>)).toBe(`event: network-board\ndata: ${CHANGED}\n\nevent: scope-ended\ndata: {}\n\n`);
    expect(seenNetwork.map((c) => c.path)).toEqual(['/networks', `/network/${NETWORK_ID}/events`]);
    expect(upstream[0]?.headers.get('accept')).toContain('text/event-stream');
  });

  it('drops the tenant board events on this stream', async () => {
    backend([frame('board', '{"serviceId":"svc-1"}'), frame('booking.updated', '{"serviceId":"svc-1"}')]);
    expect(await readAll(((await get('advisor')).body) as ReadableStream<Uint8Array>)).toBe('');
  });

  it('answers as an event stream that no cache may store or transform', async () => {
    backend([frame('network-board', CHANGED)]);
    const response = await get('advisor');
    expect(response.headers.get('content-type')).toBe('text/event-stream; charset=utf-8');
    const control = response.headers.get('cache-control') ?? '';
    expect(control).toContain('no-store');
    expect(control).toContain('no-transform');
    expect(response.headers.get('x-accel-buffering')).toBe('no');
    await response.body?.cancel();
  });

  it('closes the back end connection when the browser goes away', async () => {
    let closed = false;
    backend([frame('network-board', CHANGED)], { hold: true, onClosed: () => (closed = true) });
    const response = await get('advisor');
    const reader = (response.body as ReadableStream<Uint8Array>).getReader();
    await reader.read();
    await reader.cancel();
    await vi.waitFor(() => expect(closed).toBe(true));
  });

  it('is the one 404 for a network that is not offered, with no stream opened', async () => {
    backend([frame('network-board', CHANGED)]);
    expect((await get('advisor', TENANTS.C)).status).toBe(404);
    expect((await get('advisor', TENANTS.A, { networkId: 'net-other' })).status).toBe(404);
    expect(upstream).toEqual([]);
  });

  it('refuses a request with no networkId, or one that names more, with 400', async () => {
    for (const query of ['', 'networkId=trust-a', 'networkId=net-sample&tenant=trust-b']) {
      expect((await get('advisor', TENANTS.A, query)).status, query).toBe(400);
    }
    expect(seenNetwork).toEqual([]);
  });

  it.each(ROLES)('role %s is let in only when it is one that sees a network', async (role) => {
    backend([frame('network-board', CHANGED)]);
    const response = await get(role);
    expect(response.status).toBe(['advisor', 'clinical', 'lead', 'owner', 'exec'].includes(role) ? 200 : 403);
    await response.body?.cancel();
  });

  it('answers 503 when the back end cannot be reached', async () => {
    server.use(http.get(EVENTS, () => HttpResponse.json({}, { status: 503 })));
    expect((await get('advisor')).status).toBe(503);
  });
});
