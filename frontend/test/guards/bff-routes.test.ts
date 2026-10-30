// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES, type Role } from '@/lib/auth/session';
import { LINK_CSRF_COOKIE } from '@/lib/links/csrf';
import { BACKEND_ROOT, csrfFor, LINK, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { resetLinkRequests } from '@/test/msw/handlers/links';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// Every BFF route, found on disk, and what each must do about tenants (TEN-047, audit D 7.3). A route
// that is wrapped in `withBff` is a signed-in person's route and is checked as one automatically; any
// other route must be named in the table below, so a route cannot be added without saying which kind
// it is. Each kind then has the generated checks that follow.
//
//   session  the signed-in person's own routes (`withBff`): a session of tenant A answers 401 on tenant
//            B's host, a request that names a tenant is a 400, every answer is private and not stored.
//   link     the link pages' routes (no session): an id that exists only in tenant A, asked on tenant B's
//            host, is answered exactly as an id that exists nowhere (never a 403, never data), and a
//            staff session in the browser changes nothing.
//   sign-in  the staff sign-in: its answers are never stored.
//   beacon   the telemetry ingest: no session is a 401, never stored.
//   pairing  the wall screen's pairing routes (no person: a screen's secret).
//   pre-session  the routes a phone calls before it has a session (the reporter's set-up and PIN
//            sign-in, the registration code, the invitation read, the push key). The tenant is the
//            host (the back end resolves it; no token is sent), so such a route must never take a
//            tenant from the request, is never stored, and a write that needs the phone's CSRF token
//            (`preSession`) is refused without it, before any work. A route that signs a person in
//            makes a session for the tenant the back end names (its own test).

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

type Kind = 'session' | 'link' | 'sign-in' | 'beacon' | 'pairing' | 'pre-session';

/** The routes that are not `withBff` routes, and what each is. */
const NAMED: Record<string, Kind> = {
  'app/api/bff/telemetry/route.ts': 'beacon',
  'app/api/bff/links/[token]/route.ts': 'link',
  'app/api/bff/links/[token]/renew/route.ts': 'link',
  'app/api/bff/auth/entra/start/route.ts': 'sign-in',
  'app/api/bff/auth/entra/callback/route.ts': 'sign-in',
  'app/api/bff/screens/pairing/route.ts': 'pairing',
  'app/api/bff/screens/pairing/[id]/route.ts': 'pairing',
  'app/api/bff/screens/session/route.ts': 'pairing',
  'app/api/bff/reporter/start/route.ts': 'pre-session',
  'app/api/bff/identity/code/route.ts': 'pre-session',
  'app/api/bff/identity/code/verify/route.ts': 'pre-session',
  'app/api/bff/identity/new-phone/route.ts': 'pre-session',
  'app/api/bff/identity/new-phone/verify/route.ts': 'pre-session',
  'app/api/bff/identity/pin/route.ts': 'pre-session',
  'app/api/bff/identity/pin/verify/route.ts': 'pre-session',
  'app/api/bff/invitations/[token]/route.ts': 'pre-session',
  'app/api/bff/push/key/route.ts': 'pre-session',
};

const WITH_BFF = /\bwithBff(<[^>]*>)?\(/;

function textOf(file: string): string {
  return readFileSync(`${ROOT}${file}`, 'utf8');
}

/** `session` for a `withBff` route, the named kind for another, undefined for a route nobody has classified. */
function kindOf(file: string): Kind | undefined {
  if (file in NAMED) return NAMED[file];
  return WITH_BFF.test(textOf(file)) ? 'session' : undefined;
}

/**
 * The `withBff` routes that take an id from the caller (a dynamic segment) and have not yet said
 * `idScoped: true`, so a 403 from the back end is still a 403 there and not the one 404 of an id that
 * is nowhere (DEC-602 item 3). A route that sets it is struck from this list in the same change: the
 * list only shrinks.
 */
const ID_ROUTES_NOT_YET_SCOPED: string[] = [
  'app/api/bff/bookings/[id]/acknowledge/route.ts',
  'app/api/bff/bookings/[id]/cancel/route.ts',
  'app/api/bff/bookings/[id]/route.ts',
  'app/api/bff/cases/[ref]/options/route.ts',
  'app/api/bff/cases/[ref]/outcome/route.ts',
  'app/api/bff/cases/[ref]/route.ts',
  'app/api/bff/cases/[ref]/summary/route.ts',
  'app/api/bff/console/insight/[tab]/route.ts',
  'app/api/bff/console/sessions/[id]/events/route.ts',
  'app/api/bff/console/sessions/[id]/route.ts',
  'app/api/bff/console/sessions/[id]/ticket/route.ts',
  'app/api/bff/console/traces/[traceId]/route.ts',
  'app/api/bff/exec/alerts/[id]/acknowledge/route.ts',
  'app/api/bff/exec/alerts/[id]/snooze/route.ts',
  'app/api/bff/exec/services/[id]/route.ts',
  'app/api/bff/services/[id]/criteria/route.ts',
  'app/api/bff/services/[id]/declined/route.ts',
  'app/api/bff/services/[id]/phoned/route.ts',
];

const VERBS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'];
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

const ROOT = fileURLToPath(new URL('../..', import.meta.url));
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
  it('are each a withBff route or named in the table, and the table names no route that is not there', () => {
    expect(files.filter((f) => kindOf(f) === undefined)).toEqual([]);
    expect(Object.keys(NAMED).filter((f) => !files.includes(f))).toEqual([]);
  });

  it('use withBff or a named kind, never a bare session read: a route that reads the session itself is named and says why', () => {
    const bare = files.filter((f) => !WITH_BFF.test(textOf(f)) && /\bsessionFromRequest\b|\bgetSession\b/.test(textOf(f)));
    expect(bare).toEqual(['app/api/bff/telemetry/route.ts']);
  });

  it('say idScoped on every route that takes an id from the caller, beyond the list of those that do not yet', () => {
    const idRoutes = files.filter((f) => /\[[^\]]+\]/.test(f) && WITH_BFF.test(textOf(f)) && !/idScoped:\s*true/.test(textOf(f)));
    expect(idRoutes.sort()).toEqual([...ID_ROUTES_NOT_YET_SCOPED].sort());
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

describe.each(files.filter((f) => kindOf(f) === 'session'))('%s (session)', (file) => {
  // The role the route lets in is found by asking: the first role that is not refused with 403.
  async function allowedRole(verb: string, handler: Handler): Promise<Role> {
    for (const role of ROLES) {
      // The probe names a tenant, so a route that lets the role in stops at the 400 and never reaches its work.
      const response = await handler(
        await requestAs(A, role, { method: verb, path: '/api/bff/x?tenant=probe', csrf: UNSAFE.has(verb) ? true : undefined }),
        undefined,
      );
      if (response.status !== 403) return role;
    }
    throw new Error(`no role is let in by ${file}`);
  }

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
      const role = await allowedRole(verb, handler);
      const none = await handler(new Request(`https://${B.host}/x`, { method: verb, headers: { Host: B.host } }), undefined);
      const crossed = await handler(await requestAs(A, role, { method: verb, host: B.host, csrf: UNSAFE.has(verb) ? true : undefined }), undefined);
      expect(crossed.status, `${verb}`).toBe(401);
      expect(await crossed.text()).toBe(await none.text());
    }
  });

  it('refuses, with 400, a request that names a tenant, a scope or a network, before it does any work', async () => {
    for (const { verb, handler } of await load(file)) {
      const role = await allowedRole(verb, handler);
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
      const role = await allowedRole(verb, handler);
      const response = await handler(await requestAs(A, role, { method: verb, path: '/api/bff/x?tenant=trust-b', csrf: UNSAFE.has(verb) ? true : undefined }), undefined);
      expect(await response.text()).not.toMatch(/trust-b|tenant-b|Sample Area B/);
    }
    expect(cookieWrites).toEqual([]);
  });
});

describe.each(files.filter((f) => kindOf(f) === 'link'))('%s (link)', (file) => {
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

describe.each(files.filter((f) => kindOf(f) === 'sign-in'))('%s (sign-in)', (file) => {
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

describe.each(files.filter((f) => kindOf(f) === 'beacon'))('%s (beacon)', (file) => {
  it('is a 401, never stored, with no session', async () => {
    for (const { verb, handler } of await load(file)) {
      const response = await handler(new Request(`https://${A.host}/x`, { method: verb, headers: { Host: A.host } }));
      expect(response.status).toBe(401);
      privateNoStore(response);
    }
  });
});

describe.each(files.filter((f) => kindOf(f) === 'pre-session'))('%s (pre-session)', (file) => {
  const ctx = (token: string) => ({ params: Promise.resolve({ token }) });
  const url = () => `https://${A.host}/${file.replace('app/', '').replace('/route.ts', '').replace('[token]', 'SampleInvitationToken1')}`;

  async function ask(verb: string, handler: Handler, extra: { query?: string; headers?: Record<string, string> } = {}) {
    const headers: Record<string, string> = { Host: A.host, 'Content-Type': 'application/json', ...extra.headers };
    return handler(
      new Request(`${url()}${extra.query ?? ''}`, { method: verb, headers, body: UNSAFE.has(verb) ? '{}' : undefined }),
      ctx('SampleInvitationToken1'),
    );
  }

  it('is never stored by a cache, whatever it answers', async () => {
    for (const { verb, handler } of await load(file)) privateNoStore(await ask(verb, handler));
  });

  it('takes no tenant from the request: a query key or a header that names one changes nothing and is not echoed', async () => {
    for (const { verb, handler } of await load(file)) {
      const plain = await ask(verb, handler);
      const named = await ask(verb, handler, { query: `?tenant=${B.id}&scope=network`, headers: { 'X-Tenant-Id': B.id } });
      expect(named.status, verb).toBe(plain.status);
      expect(await named.text(), verb).not.toMatch(/trust-b|tenant-b|Sample Area B|net-sample/);
    }
  });

  it('reads no session: a session of tenant A in the browser changes nothing for a phone on tenant B’s host', async () => {
    for (const { verb, handler } of await load(file)) {
      const plain = await handler(
        new Request(`https://${B.host}/x`, { method: verb, headers: { Host: B.host, 'Content-Type': 'application/json' }, body: UNSAFE.has(verb) ? '{}' : undefined }),
        ctx('SampleInvitationToken1'),
      );
      const staff = await requestAs(A, 'advisor', { method: verb, host: B.host, headers: { 'Content-Type': 'application/json' }, body: UNSAFE.has(verb) ? '{}' : undefined });
      const crossed = await handler(staff, ctx('SampleInvitationToken1'));
      expect(crossed.status, verb).toBe(plain.status);
    }
  });
});

const WRITES_NEED_PHONE_CSRF = files.filter((f) => kindOf(f) === 'pre-session' && /\bpreSession\(/.test(textOf(f)));
const WRITES_TAKE_JSON_ONLY = files.filter((f) => kindOf(f) === 'pre-session' && !/\bpreSession\(/.test(textOf(f)) && /\bjsonBody\(/.test(textOf(f)));

describe.each(WRITES_NEED_PHONE_CSRF)('%s (pre-session write with the phone’s CSRF token)', (file) => {
  it('refuses a write with no CSRF token of this phone, 403 before any work', async () => {
    for (const { verb, handler } of await load(file)) {
      if (!UNSAFE.has(verb)) continue;
      const response = await handler(
        new Request(`https://${A.host}/x`, { method: verb, headers: { Host: A.host, 'Content-Type': 'application/json' }, body: '{}' }),
        undefined,
      );
      expect(response.status, verb).toBe(403);
      expect(await response.json()).toEqual({ code: 'csrf' });
    }
  });
});

describe.each(WRITES_TAKE_JSON_ONLY)('%s (pre-session write, JSON only)', (file) => {
  it('refuses a write in another content type with 400, before any work', async () => {
    for (const { verb, handler } of await load(file)) {
      if (!UNSAFE.has(verb)) continue;
      const response = await handler(
        new Request(`https://${A.host}/x`, { method: verb, headers: { Host: A.host, 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'phone=07700900123' }),
        undefined,
      );
      expect(response.status, verb).toBe(400);
    }
  });
});

it('has at least one pre-session write of each kind (the generated checks are not vacuous)', () => {
  expect(WRITES_NEED_PHONE_CSRF.length).toBeGreaterThan(0);
  expect(WRITES_TAKE_JSON_ONLY.length).toBeGreaterThan(0);
});
