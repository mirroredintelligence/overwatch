// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE, TOKEN_ORG_A, TOKEN_ORG_B } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { frame, readAll, streamOf } from '@/test/sse';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const URL_ = 'https://app.test/api/bff/events';
const EVENTS = `${BACKEND_BASE}/events`;
const SSE = 'text/event-stream';
const SERVICE = '{"serviceId":"a1","changedAt":"2026-10-23T13:12:00Z"}';

function session(role: Role, backendToken: string = TOKEN_ORG_A): Session {
  return {
    role,
    services: [],
    sub: 'screen-1',
    backendToken,
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(
  role: Role | null,
  options: { token?: string; url?: string; headers?: HeadersInit; signal?: AbortSignal } = {},
) {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role, options.token));
  return GET(requestWithCookies(options.url ?? URL_, cookies, { headers: options.headers, signal: options.signal }));
}

const upstreamRequests: Request[] = [];

/** The back end's /events: sends these chunks, in order, then ends (or stays open when held). */
function backend(chunks: string[], options: { hold?: boolean; onCancel?: () => void } = {}) {
  server.use(
    http.get(EVENTS, ({ request }) => {
      upstreamRequests.push(request.clone());
      return new HttpResponse(streamOf(chunks, options), { headers: { 'Content-Type': SSE } });
    }),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  upstreamRequests.length = 0;
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/events: the relay', () => {
  it('forwards a board event from the back end stream', async () => {
    backend([frame('board', SERVICE)]);

    const response = await get('wall');

    expect(response.status).toBe(200);
    expect(await readAll(response.body as ReadableStream<Uint8Array>)).toBe(`event: board\ndata: ${SERVICE}\n\n`);
  });

  it('forwards board.updated and booking.updated, and drops an event type it does not know', async () => {
    backend([
      frame('board.updated', SERVICE),
      frame('unknown.thing', '{"patient":"someone"}'),
      frame('booking.updated', SERVICE),
    ]);

    const text = await readAll(((await get('advisor')).body) as ReadableStream<Uint8Array>);

    expect(text).toBe(`event: board.updated\ndata: ${SERVICE}\n\nevent: booking.updated\ndata: ${SERVICE}\n\n`);
    expect(text).not.toContain('someone');
  });

  it('keeps the connection alive with a fixed comment and does not pass the back end comment text on', async () => {
    backend([': keep-alive\n\n', ': internal host 10.0.0.5\n\n', frame('board', SERVICE)]);

    const text = await readAll(((await get('wall')).body) as ReadableStream<Uint8Array>);

    expect(text).not.toContain('10.0.0.5');
    expect(text).toContain(`event: board\ndata: ${SERVICE}\n\n`);
    expect(text.startsWith(': keep-alive\n\n')).toBe(true);
  });

  it('answers as an event stream that no cache or proxy may store or transform, and that is not buffered', async () => {
    backend([frame('board', SERVICE)]);

    const response = await get('wall');

    expect(response.headers.get('content-type')).toBe('text/event-stream; charset=utf-8');
    const cacheControl = response.headers.get('cache-control') ?? '';
    expect(cacheControl).toContain('no-store');
    expect(cacheControl).toContain('no-transform');
    expect(response.headers.get('x-accel-buffering')).toBe('no');
    expect(response.headers.get('content-length')).toBeNull();
    await response.body?.cancel();
  });

  it('streams through: the first event reaches the browser while the back end connection is still open', async () => {
    backend([frame('board', SERVICE)], { hold: true });
    const response = await get('wall');
    const reader = (response.body as ReadableStream<Uint8Array>).getReader();

    const first = await Promise.race([
      reader.read(),
      new Promise<'waited'>((resolve) => setTimeout(() => resolve('waited'), 1_000)),
    ]);

    expect(first).not.toBe('waited');
    expect(new TextDecoder().decode((first as ReadableStreamReadResult<Uint8Array>).value)).toBe(
      `event: board\ndata: ${SERVICE}\n\n`,
    );
    await reader.cancel();
  });

  it('closes the back end stream when the browser goes away (cancelling the body)', async () => {
    const onCancel = vi.fn();
    backend([frame('board', SERVICE)], { hold: true, onCancel });
    const response = await get('wall');
    const reader = (response.body as ReadableStream<Uint8Array>).getReader();
    await reader.read();

    await reader.cancel();
    await vi.waitFor(() => expect(onCancel).toHaveBeenCalled());
  });

  it('closes the back end stream when the request is aborted', async () => {
    const onCancel = vi.fn();
    backend([frame('board', SERVICE)], { hold: true, onCancel });
    const controller = new AbortController();
    const response = await get('wall', { signal: controller.signal });
    const reader = (response.body as ReadableStream<Uint8Array>).getReader();
    await reader.read();

    controller.abort();

    await vi.waitFor(() => expect(onCancel).toHaveBeenCalled());
    await reader.cancel().catch(() => undefined);
  });

  it('ends its own stream when the back end ends, so the browser reconnects', async () => {
    backend([frame('board', SERVICE)]);

    const text = await readAll(((await get('wall')).body) as ReadableStream<Uint8Array>);

    expect(text).toBe(`event: board\ndata: ${SERVICE}\n\n`);
  });
});

describe('GET /api/bff/events: who may listen', () => {
  it('answers 401 with no session and does not open the back end stream', async () => {
    backend([]);

    const response = await get(null);

    expect(response.status).toBe(401);
    expect(upstreamRequests).toHaveLength(0);
  });

  it.each<Role>(['wall', 'advisor', 'lead', 'exec'])('lets a %s session listen', async (role) => {
    backend([]);

    const response = await get(role);

    expect(response.status).toBe(200);
    expect(upstreamRequests).toHaveLength(1);
    await response.body?.cancel();
  });

  it.each<Role>(['reporter', 'anonymous-link', 'support', 'audit', 'clinical', 'owner'])(
    'answers 403 for a %s session and does not open the back end stream',
    async (role) => {
      backend([]);

      expect((await get(role)).status).toBe(403);
      expect(upstreamRequests).toHaveLength(0);
    },
  );

  it('answers with the back end status when it refuses the stream: 401, 403 and 404 pass through', async () => {
    for (const status of [401, 403, 404]) {
      server.use(http.get(EVENTS, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status })));

      const response = await get('wall');

      expect(response.status).toBe(status);
      expect(response.headers.get('content-type')).not.toContain(SSE);
    }
  });

  it('answers 503 when the back end cannot be reached, and 502 when it does not send an event stream', async () => {
    server.use(http.get(EVENTS, () => HttpResponse.error()));
    expect((await get('wall')).status).toBe(503);

    server.use(http.get(EVENTS, () => HttpResponse.json({ not: 'a stream' })));
    expect((await get('wall')).status).toBe(502);
  });

  it('is never cached when it refuses, either', async () => {
    expect((await get(null)).headers.get('cache-control')).toBe('no-store');
    expect((await get('reporter')).headers.get('cache-control')).toBe('no-store');
  });
});

describe('GET /api/bff/events: one organisation, the session’s own (DEC-130, DEC-132)', () => {
  it('opens the back end stream with the session token, no query string and no tenant or organisation header', async () => {
    backend([]);

    await (await get('wall')).body?.cancel();

    expect(upstreamRequests).toHaveLength(1);
    const request = upstreamRequests[0];
    expect(request.method).toBe('GET');
    expect(request.headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect(new URL(request.url).search).toBe('');
    expect(new URL(request.url).pathname).toBe('/fhir/events');
    for (const name of request.headers.keys()) expect(name).not.toMatch(/tenant|organi[sz]ation|scope|network/i);
  });

  it('ignores a tenant, organisation, scope or network in the query string and in the request headers', async () => {
    backend([]);

    await (
      await get('wall', {
        url: `${URL_}?tenant=${TOKEN_ORG_B}&organisation=Other&scope=network&network=n1`,
        headers: {
          'X-Tenant-Id': TOKEN_ORG_B,
          'X-Organisation': 'Other',
          'X-Scope': 'network',
          Authorization: `Bearer ${TOKEN_ORG_B}`,
        },
      })
    ).body?.cancel();

    const request = upstreamRequests[0];
    expect(request.headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect(new URL(request.url).search).toBe('');
    expect([...request.headers.keys()].join(' ')).not.toMatch(/tenant|organi[sz]ation|scope/i);
  });

  it('uses the token of the session it is given, so another session opens its own stream', async () => {
    backend([]);

    await (await get('wall', { token: TOKEN_ORG_B })).body?.cancel();

    expect(upstreamRequests[0].headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_B}`);
  });
});
