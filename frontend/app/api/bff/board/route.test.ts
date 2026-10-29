// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BOARD_A, BOARD_B } from '@/test/fixtures/board';
import {
  BACKEND_BASE,
  BOARD_URL,
  resetSeenBoardRequests,
  seenBoardRequests,
  TOKEN_ORG_A,
  TOKEN_ORG_B,
} from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const URL_ = 'https://app.test/api/bff/board';

function session(role: Role, backendToken: string = TOKEN_ORG_A): Session {
  return {
    role,
    services: [],
    sub: 'user-1',
    backendToken,
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(role: Role | null, options: { token?: string; url?: string; headers?: HeadersInit } = {}) {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role, options.token));
  return GET(requestWithCookies(options.url ?? URL_, cookies, { headers: options.headers }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  resetSeenBoardRequests();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/board', () => {
  it.each<Role>(['advisor', 'wall', 'lead', 'exec'])('answers 200 with the Board as JSON for a %s session', async (role) => {
    const response = await get(role);

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('application/json');
    expect(await response.json()).toEqual(BOARD_A);
  });

  it('answers 403 for a reporter session and does not call the back end', async () => {
    const response = await get('reporter');

    expect(response.status).toBe(403);
    expect(seenBoardRequests).toHaveLength(0);
  });

  it.each<Role>(['anonymous-link', 'support', 'audit', 'clinical', 'owner'])(
    'answers 403 for a %s session',
    async (role) => {
      expect((await get(role)).status).toBe(403);
      expect(seenBoardRequests).toHaveLength(0);
    },
  );

  it('answers 401 with no session and does not call the back end', async () => {
    const response = await get(null);

    expect(response.status).toBe(401);
    expect(seenBoardRequests).toHaveLength(0);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('no-store');
    expect((await get('reporter')).headers.get('cache-control')).toBe('no-store');
  });

  it('calls the back end with the session token and nothing else that names an organisation', async () => {
    await get('advisor');

    expect(seenBoardRequests).toHaveLength(1);
    const sent = seenBoardRequests[0];
    const url = new URL(sent.url);
    expect(sent.method).toBe('GET');
    expect(sent.headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect(url.search).toBe('');
    expect([...sent.headers.keys()].filter((k) => /tenant|organi[sz]ation|scope/i.test(k))).toEqual([]);
  });

  it('takes no organisation from the query string or a header: it answers for the session only', async () => {
    const response = await get('advisor', {
      url: `${URL_}?tenant=${TOKEN_ORG_B}&organisation=Neighbouring&scope=network`,
      headers: {
        'X-Tenant-Id': TOKEN_ORG_B,
        'X-Organisation': 'Neighbouring',
        Authorization: `Bearer ${TOKEN_ORG_B}`,
      },
    });

    expect(await response.json()).toEqual(BOARD_A);
    expect(seenBoardRequests).toHaveLength(1);
    expect(new URL(seenBoardRequests[0].url).search).toBe('');
    expect(seenBoardRequests[0].headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect([...seenBoardRequests[0].headers.keys()].filter((k) => /tenant|organi[sz]ation/i.test(k))).toEqual([]);
  });

  it('answers each session with the board for its own token, not the other organisation’s', async () => {
    const forA = JSON.stringify(await (await get('wall', { token: TOKEN_ORG_A })).json());
    const forB = JSON.stringify(await (await get('wall', { token: TOKEN_ORG_B })).json());

    for (const e of BOARD_B.entries) expect(forA).not.toContain(e.name);
    for (const e of BOARD_A.entries) expect(forB).not.toContain(e.name);
    expect(JSON.parse(forB)).toEqual(BOARD_B);
  });

  it('passes a back-end refusal on with the fixed text and no back-end detail', async () => {
    server.use(
      http.get(BOARD_URL, () =>
        HttpResponse.json(
          { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login', diagnostics: 'secret detail' }] },
          { status: 401 },
        ),
      ),
    );

    const response = await get('advisor');
    const text = await response.text();

    expect(response.status).toBe(401);
    expect(text).not.toContain('secret detail');
  });

  it('answers 503 when the back end cannot be reached', async () => {
    server.use(http.get(BOARD_URL, () => HttpResponse.error()));

    expect((await get('advisor')).status).toBe(503);
  });

  it('answers 502, with no figures, when the back end sends a board it cannot read', async () => {
    server.use(
      http.get(BOARD_URL, () =>
        HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'entry', part: [] }] }),
      ),
    );

    const response = await get('advisor');
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ code: 'exception', message: 'Something went wrong. Try again.' });
  });

  it('puts no token in the response', async () => {
    const response = await get('advisor');
    const text = await response.text();

    expect(response.status).toBe(200);
    expect(text).not.toContain(TOKEN_ORG_A);
    expect(text).not.toContain('backendToken');
  });
});
