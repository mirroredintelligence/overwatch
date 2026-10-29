// @vitest-environment node
import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { canAccess } from '@/lib/auth/access';
import { ROLES, sealSession, SESSION_COOKIE, type Role, type Session } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { config, proxy } from './proxy';

// The role guard (W09). The session is read from the sealed cookie and from
// nothing else: not the query string, not a header.

const BASE = 'https://capacity.example.test';

beforeEach(() => vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET));
afterEach(() => vi.unstubAllEnvs());

function sessionFor(role: Role, overrides: Partial<Session> = {}): Session {
  return {
    role,
    services: [],
    sub: 'aaaaaaaa-0000-4000-8000-000000000001',
    backendToken: 'backend-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
    ...overrides,
  };
}

async function request(path: string, role?: Role, init: { cookie?: string; headers?: Record<string, string> } = {}) {
  const headers = new Headers(init.headers);
  const cookie = init.cookie ?? (role ? `${SESSION_COOKIE}=${await sealSession(sessionFor(role))}` : undefined);
  if (cookie) headers.set('cookie', cookie);
  return new NextRequest(`${BASE}${path}`, { headers });
}

function redirectedTo(response: Response | undefined): string | null {
  if (!response) return null;
  const location = response.headers.get('location');
  if (!location || response.status < 300 || response.status > 399) return null;
  const url = new URL(location);
  return url.pathname + url.search;
}

function rewrittenTo(response: Response | undefined): string | null {
  const target = response?.headers.get('x-middleware-rewrite');
  if (!target) return null;
  const url = new URL(target);
  return url.pathname + url.search;
}

function passes(response: Response | undefined): boolean {
  return response?.headers.get('x-middleware-next') === '1';
}

describe('no session', () => {
  it('sends /lead to /sign-in?next=%2Flead', async () => {
    const response = await proxy(await request('/lead'));
    expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead');
  });

  it('keeps the query string in next', async () => {
    const response = await proxy(await request('/lead?tab=late'));
    expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead%3Ftab%3Dlate');
  });

  it.each(['/advisor', '/advisor/case/4821', '/clinical', '/owner/criteria', '/planning', '/console'])(
    'sends %s to sign-in',
    async (path) => {
      const response = await proxy(await request(path));
      expect(redirectedTo(response)).toBe(`/sign-in?next=${encodeURIComponent(path)}`);
    },
  );

  it('does not let the browser cache the answer', async () => {
    const response = await proxy(await request('/lead'));
    expect(response?.headers.get('cache-control')).toBe('no-store');
  });

  it.each(['/Lead', '/%6Cead', '//lead', '/lead/', '/x%2F..%2Flead'])('also guards the path written as %s', async (path) => {
    const response = await proxy(await request(path));
    expect(redirectedTo(response)).toMatch(/^\/sign-in/);
  });

  it('leaves unguarded paths alone, and does not need the session secret for them', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    for (const path of ['/', '/screen', '/screen/pair', '/sign-in', '/forbidden', '/api/bff/board', '/case/4821']) {
      const response = await proxy(await request(path));
      expect(response === undefined || passes(response)).toBe(true);
      expect(redirectedTo(response)).toBeNull();
    }
  });
});

describe('a session that is not good', () => {
  it('sends an expired session to sign-in', async () => {
    const past = new Date(Date.now() - 9 * 3_600_000);
    const sealed = await sealSession(sessionFor('lead', { expiresAt: new Date(past.getTime() + 8 * 3_600_000).toISOString() }), past);
    const response = await proxy(await request('/lead', undefined, { cookie: `${SESSION_COOKIE}=${sealed}` }));
    expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead');
  });

  it('sends a cookie that is not a session, or was sealed with another key, to sign-in', async () => {
    const other = Buffer.alloc(32, 1).toString('base64');
    vi.stubEnv('SESSION_SECRET', other);
    const foreign = await sealSession(sessionFor('lead'));
    vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
    for (const value of ['garbage', foreign, '']) {
      const response = await proxy(await request('/lead', undefined, { cookie: `${SESSION_COOKIE}=${value}` }));
      expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead');
    }
  });

  it('fails closed when the session secret is not set: an error, never a pass', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    await expect(proxy(await request('/lead', undefined, { cookie: `${SESSION_COOKIE}=anything` }))).rejects.toThrow('SESSION_SECRET');
  });
});

describe('a signed-in role', () => {
  it('sends an advisor on /lead to the forbidden page', async () => {
    const response = await proxy(await request('/lead', 'advisor'));
    expect(rewrittenTo(response)).toBe('/forbidden');
    expect(response?.status).toBe(403);
  });

  it('lets an advisor into /advisor/case/4821', async () => {
    const response = await proxy(await request('/advisor/case/4821', 'advisor'));
    expect(passes(response)).toBe(true);
    expect(redirectedTo(response)).toBeNull();
    expect(rewrittenTo(response)).toBeNull();
  });

  it('does not let the browser cache a guarded page, allowed or not', async () => {
    expect((await proxy(await request('/advisor', 'advisor')))?.headers.get('cache-control')).toBe('no-store');
    expect((await proxy(await request('/lead', 'advisor')))?.headers.get('cache-control')).toBe('no-store');
  });

  const guarded = ['/advisor', '/advisor/case/4821', '/clinical', '/lead', '/owner', '/owner/criteria', '/planning', '/console'];
  it.each(ROLES.flatMap((role) => guarded.map((path) => [role, path] as const)))('%s on %s', async (role, path) => {
    const response = await proxy(await request(path, role));
    if (canAccess(role, path)) {
      expect(passes(response)).toBe(true);
    } else {
      expect(rewrittenTo(response)).toBe('/forbidden');
    }
  });

  it('gives a wall screen, a reporter and a link no staff page', async () => {
    for (const role of ['wall', 'reporter', 'anonymous-link', 'audit'] as Role[]) {
      for (const path of ['/advisor', '/clinical', '/lead', '/owner', '/planning', '/console']) {
        expect(rewrittenTo(await proxy(await request(path, role)))).toBe('/forbidden');
      }
    }
  });

  it('takes the role from the cookie alone: a query string or a header cannot raise it', async () => {
    const attempts: [string, Record<string, string>][] = [
      ['/lead?role=lead', {}],
      ['/lead?role=lead&tenant=trust-b', {}],
      ['/lead', { 'x-role': 'lead', 'x-diucs-role': 'lead', authorization: 'Bearer lead' }],
    ];
    for (const [path, headers] of attempts) {
      expect(rewrittenTo(await proxy(await request(path, 'advisor', { headers })))).toBe('/forbidden');
    }
  });
});

describe('matcher', () => {
  const patterns = config.matcher.map((m) => new RegExp(`^${m}$`));
  const covered = (path: string) => patterns.some((p) => p.test(path));

  it('covers every page path, so a rewritten or odd path still reaches the guard', () => {
    for (const path of ['/lead', '/advisor/case/4821', '//lead', '/%6Cead', '/', '/sign-in']) expect(covered(path)).toBe(true);
  });

  it('leaves out the static files Next serves', () => {
    for (const path of ['/_next/static/chunks/a.js', '/_next/image', '/favicon.ico']) expect(covered(path)).toBe(false);
  });
});
