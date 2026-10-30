// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LINK_CSRF_COOKIE } from '@/lib/links/csrf';
import { BACKEND_ROOT, csrfFor, LINK, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { resetLinkRequests } from '@/test/msw/handlers/links';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// Every BFF route, found on disk, and what each must do about tenants (TEN-047, audit D 7.3). A new
// route file that is not in the table below fails the test, so a route cannot be added without saying
// which kind it is; each kind then has the generated checks that follow.
//
//   session  the signed-in person's own routes (`withBff`): a session of tenant A answers 401 on tenant
//            B's host, a request that names a tenant is a 400, every answer is private and not stored.
//   link     the link pages' routes (no session): an id that exists only in tenant A, asked on tenant B's
//            host, is answered exactly as an id that exists nowhere (never a 403, never data), and a
//            staff session in the browser changes nothing.
//   sign-in  the staff sign-in: its answers are never stored.
//   beacon   the telemetry ingest: no session is a 401, never stored.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

type Kind =
  | { kind: 'session'; role: 'advisor' | 'wall' }
  | { kind: 'link' }
  | { kind: 'sign-in' }
  | { kind: 'beacon' };

const ROUTES: Record<string, Kind> = {
  'app/api/bff/session/route.ts': { kind: 'session', role: 'advisor' },
  'app/api/bff/board/route.ts': { kind: 'session', role: 'advisor' },
  'app/api/bff/events/route.ts': { kind: 'session', role: 'wall' },
  'app/api/bff/telemetry/route.ts': { kind: 'beacon' },
  'app/api/bff/links/[token]/route.ts': { kind: 'link' },
  'app/api/bff/links/[token]/renew/route.ts': { kind: 'link' },
  'app/api/bff/auth/entra/start/route.ts': { kind: 'sign-in' },
  'app/api/bff/auth/entra/callback/route.ts': { kind: 'sign-in' },
};

const VERBS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'];
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

const modules = import.meta.glob<Record<string, unknown>>('../../app/api/bff/**/route.ts');
const files = Object.keys(modules).map((key) => key.replace('../../', '')).sort();

type Handler = (request: Request, context?: unknown) => Promise<Response> | Response;

async function load(file: string): Promise<{ verb: string; handler: Handler }[]> {
  const mod = await modules[`../../${file}`]!();
  return Object.entries(mod)
    .filter(([name]) => VERBS.includes(name))
    .map(([verb, handler]) => ({ verb, handler: handler as Handler }));
}

const A = TENANTS.A;
const B = TENANTS.B;
const privateNoStore = (response: Response) => {
  const control = (response.headers.get('cache-control') ?? '').toLowerCase();
  expect(control).toContain('no-store');
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  resetLinkRequests();
});
afterEach(() => vi.unstubAllEnvs());

describe('the routes on disk', () => {
  it('are all in the table, and the table names no route that is not there', () => {
    expect(files).toEqual(Object.keys(ROUTES).sort());
  });

  it('export only HTTP methods, each a function', async () => {
    for (const file of files) {
      const mod = await modules[`../../${file}`]!();
      for (const [name, value] of Object.entries(mod)) {
        if (['dynamic', 'runtime', 'revalidate', 'fetchCache', 'maxDuration'].includes(name)) continue;
        expect(VERBS, `${file} exports ${name}`).toContain(name);
        expect(typeof value, `${file} ${name}`).toBe('function');
      }
    }
  });

  it('export at least one method', async () => {
    for (const file of files) expect((await load(file)).length, file).toBeGreaterThan(0);
  });

  it('set no cache, revalidate or static directive that would let a framework keep an answer', async () => {
    for (const file of files) {
      const mod = await modules[`../../${file}`]!();
      expect(mod.revalidate, file).toBeUndefined();
      expect(mod.fetchCache, file).toBeUndefined();
      if (mod.dynamic !== undefined) expect(mod.dynamic, file).toBe('force-dynamic');
    }
  });
});

describe.each(Object.entries(ROUTES).filter(([, k]) => k.kind === 'session'))('%s (session)', (file, kind) => {
  const role = (kind as { role: 'advisor' | 'wall' }).role;

  it('answers 401 no-session, private and not stored, to a request with no session', async () => {
    for (const { verb, handler } of await load(file)) {
      const response = await handler(new Request(`https://${A.host}/x`, { method: verb, headers: { Host: A.host } }), undefined);
      expect(response.status, `${verb}`).toBe(401);
      expect(await response.json()).toEqual({ code: 'no-session' });
      privateNoStore(response);
    }
  });

  it('answers a session of tenant A, sent to tenant B’s host, exactly as no session', async () => {
    for (const { verb, handler } of await load(file)) {
      const none = await handler(new Request(`https://${B.host}/x`, { method: verb, headers: { Host: B.host } }), undefined);
      const crossed = await handler(await requestAs(A, role, { method: verb, host: B.host, csrf: UNSAFE.has(verb) ? true : undefined }), undefined);
      expect(crossed.status, `${verb}`).toBe(401);
      expect(await crossed.text()).toBe(await none.text());
    }
  });

  it('refuses, with 400, a request that names a tenant, a scope or a network, before it does any work', async () => {
    for (const { verb, handler } of await load(file)) {
      for (const query of ['tenant=trust-b', 'scope=network', 'networkId=net-sample']) {
        const response = await handler(
          await requestAs(A, role, { method: verb, path: `/api/bff/x?${query}`, csrf: UNSAFE.has(verb) ? true : undefined }),
          undefined,
        );
        expect(response.status, `${verb} ${query}`).toBe(400);
        expect(await response.json()).toEqual({ code: 'invalid' });
        privateNoStore(response);
      }
      const header = await handler(await requestAs(A, role, { method: verb, headers: { 'X-Tenant-Id': B.id }, csrf: UNSAFE.has(verb) ? true : undefined }), undefined);
      expect(header.status, `${verb} header`).toBe(400);
    }
  });

  it('answers a request that is refused with no cookie of its own and nothing about another tenant', async () => {
    for (const { verb, handler } of await load(file)) {
      const response = await handler(await requestAs(A, role, { method: verb, path: '/api/bff/x?tenant=trust-b', csrf: UNSAFE.has(verb) ? true : undefined }), undefined);
      expect(await response.text()).not.toMatch(/trust-b|tenant-b|Sample Area B/);
    }
    expect(cookieWrites).toEqual([]);
  });
});

describe.each(Object.entries(ROUTES).filter(([, k]) => k.kind === 'link'))('%s (link)', (file) => {
  const url = (token: string) => `https://${B.host}/api/bff/links/${token}${file.endsWith('renew/route.ts') ? '/renew' : ''}`;
  const ctx = (token: string) => ({ params: Promise.resolve({ token }) });
  const ABSENT = 'NoSuchLinkTokenAnywhere1';

  async function ask(verb: string, handler: Handler, token: string, host: string) {
    const path = new URL(url(token)).pathname;
    // A POST carries the link's own CSRF pair, as the page sends it, so the request reaches the back end.
    const cookies: Record<string, string> = verb === 'POST' && !path.endsWith('/renew') ? { [LINK_CSRF_COOKIE]: csrfFor(token) } : {};
    const headers: Record<string, string> = { Host: host, 'Content-Type': 'application/json' };
    if (verb === 'POST' && !path.endsWith('/renew')) headers['X-CSRF-Token'] = csrfFor(token);
    const request = requestWithCookies(`https://${host}${path}`, cookies, {
      method: verb,
      headers,
      body: verb === 'POST' ? JSON.stringify({ action: 'confirm' }) : undefined,
    });
    return handler(request, ctx(token));
  }

  it('answers a link that exists only in tenant A, asked on tenant B’s host, exactly as a link that exists nowhere', async () => {
    for (const { verb, handler } of await load(file)) {
      const other = await ask(verb, handler, LINK.recorded, B.host);
      const absent = await ask(verb, handler, ABSENT, B.host);
      expect(other.status, verb).toBe(absent.status);
      expect(await other.text(), verb).toBe(await absent.text());
      expect([403, 401]).not.toContain(other.status);
    }
  });

  it('is not vacuous: the same link on tenant A’s own host is a different answer', async () => {
    for (const { verb, handler } of await load(file)) {
      if (file.endsWith('renew/route.ts')) continue;
      const own = await ask(verb, handler, LINK.recorded, TENANT_HOST);
      const absent = await ask(verb, handler, ABSENT, B.host);
      expect(await own.text(), verb).not.toBe(await absent.text());
    }
  });

  it('answers the same with a staff session in the browser, and writes no cookie of the staff session', async () => {
    for (const { verb, handler } of await load(file)) {
      resetCookieWrites();
      const plain = await ask(verb, handler, LINK.recorded, TENANT_HOST);
      const names = cookieWrites.map((w) => w.name);
      resetCookieWrites();
      const staff = await requestAs(A, 'advisor', { method: verb, host: TENANT_HOST, csrf: true, path: new URL(url(LINK.recorded)).pathname });
      const cookiePair = staff.headers.get('cookie') ?? '';
      const path = new URL(url(LINK.recorded)).pathname;
      const link = verb === 'POST' && !path.endsWith('/renew') ? `; ${LINK_CSRF_COOKIE}=${csrfFor(LINK.recorded)}` : '';
      const withStaff = new Request(`https://${TENANT_HOST}${path}`, {
        method: verb,
        headers: {
          Host: TENANT_HOST,
          Cookie: `${cookiePair}${link}`,
          'Content-Type': 'application/json',
          ...(verb === 'POST' && !path.endsWith('/renew') ? { 'X-CSRF-Token': csrfFor(LINK.recorded) } : {}),
        },
        body: verb === 'POST' ? JSON.stringify({ action: 'confirm' }) : undefined,
      });
      const answer = await handler(withStaff, ctx(LINK.recorded));
      expect(answer.status, verb).toBe(plain.status);
      expect(await answer.text(), verb).toBe(await plain.text());
      expect(cookieWrites.map((w) => w.name), verb).toEqual(names);
      expect(cookieWrites.some((w) => w.name === 'diucs_session' || w.name === 'diucs_csrf')).toBe(false);
    }
  });

  it('is never stored by a cache', async () => {
    for (const { verb, handler } of await load(file)) {
      privateNoStore(await ask(verb, handler, LINK.recorded, TENANT_HOST));
      privateNoStore(await ask(verb, handler, ABSENT, B.host));
    }
  });
});

describe.each(Object.entries(ROUTES).filter(([, k]) => k.kind === 'sign-in'))('%s (sign-in)', (file) => {
  it('is never stored, and takes no tenant from the request', async () => {
    vi.stubEnv('ENTRA_CLIENT_ID', 'client');
    vi.stubEnv('ENTRA_CLIENT_SECRET', 'secret');
    for (const { verb, handler } of await load(file)) {
      const response = await handler(
        new Request(`https://${A.host}/x?tenant=${B.id}`, { method: verb, headers: { Host: A.host, 'X-Tenant-Id': B.id, 'Content-Type': 'application/x-www-form-urlencoded' }, body: verb === 'POST' ? '' : undefined }),
        undefined,
      );
      privateNoStore(response);
      expect(response.headers.get('location') ?? '').not.toContain(B.id);
    }
  });
});

describe.each(Object.entries(ROUTES).filter(([, k]) => k.kind === 'beacon'))('%s (beacon)', (file) => {
  it('is a 401, never stored, with no session', async () => {
    for (const { verb, handler } of await load(file)) {
      const response = await handler(new Request(`https://${A.host}/x`, { method: verb, headers: { Host: A.host } }));
      expect(response.status).toBe(401);
      privateNoStore(response);
    }
  });
});
