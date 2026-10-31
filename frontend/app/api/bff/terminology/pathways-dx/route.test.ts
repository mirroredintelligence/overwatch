// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The back end mounts the terminology routes at its root, not under /fhir (R16).
const ORIGIN = BACKEND_BASE.replace(/\/fhir$/, '');
const seen: { path: string; query: string | null; token: string | null }[] = [];

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(role: Role | null, query: string | null): Promise<Response> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const url = `https://app.test/api/bff/terminology/pathways-dx${query === null ? '' : `?q=${encodeURIComponent(query)}`}`;
  return GET(requestWithCookies(url, cookies));
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(`${ORIGIN}/terminology/pathways-dx`, ({ request }) => {
      const url = new URL(request.url);
      seen.push({ path: url.pathname, query: url.searchParams.get('q'), token: request.headers.get('authorization') });
      return HttpResponse.json(
        Array.from({ length: 21 }, (_, index) => ({ code: `Dx${index}0`, display: `Sample ${index}` })),
      );
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/terminology/pathways-dx (W12)', () => {
  it('searches the back end at its root with the text and the session token, and answers the list', async () => {
    const response = await get('advisor', 'fa');

    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0]).toEqual({ path: '/terminology/pathways-dx', query: 'fa', token: 'Bearer token-for-advisor' });
    expect(await response.json()).toHaveLength(20);
  });

  it('answers at most 20 items, each with a code and a display', async () => {
    const body = (await (await get('advisor', 'fa')).json()) as { code: string; display: string }[];
    expect(body[0]).toEqual({ code: 'Dx00', display: 'Sample 0' });
    expect(body.every((item) => typeof item.code === 'string' && typeof item.display === 'string')).toBe(true);
  });

  it('leaves out a code the back end would refuse to record, so the picker never offers one (KI-625)', async () => {
    server.use(
      http.get(`${ORIGIN}/terminology/pathways-dx`, () =>
        HttpResponse.json([
          { code: 'Dx02', display: 'Fits' },
          { code: 'PD-101', display: 'Has a hyphen' },
          { code: 'D', display: 'Too short' },
          { code: 'Dx01234567890', display: 'Too long' },
          { code: 'dx 03', display: 'Has a space' },
          { code: 'DX0121', display: 'Fits too' },
        ]),
      ),
    );

    const body = (await (await get('advisor', 'fa')).json()) as { code: string }[];

    expect(body.map((item) => item.code)).toEqual(['Dx02', 'DX0121']);
  });

  it('answers 403 for a clinical or reporter session, without a search', async () => {
    expect((await get('reporter', 'fa')).status).toBe(403);
    expect((await get('clinical', 'fa')).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it.each([
    ['no text', null],
    ['one character', 'f'],
    ['one character with spaces', '  f  '],
    ['text longer than 64 characters', 'x'.repeat(65)],
  ])('refuses %s with 400 and does not search', async (_label, query) => {
    expect((await get('advisor', query)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 502 when the back end sends something other than a list', async () => {
    server.use(http.get(`${ORIGIN}/terminology/pathways-dx`, () => HttpResponse.json({ code: 'Dx1' })));

    expect((await get('advisor', 'fa')).status).toBe(502);
  });

  it('is never cached', async () => {
    expect((await get('advisor', 'fa')).headers.get('cache-control')).toBe('private, no-store');
  });
});
