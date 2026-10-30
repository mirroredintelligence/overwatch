// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { cookieWrites, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { csrfFor, requestAs, sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { withBff } from './handler';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session. (SESSION_SECRET is set here, before the first test.)
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const TOKEN = csrfFor(sessionFor(TENANTS.A, 'advisor'));
const URL_ = `https://${TENANTS.A.host}/api/bff/thing`;

function sample(role: Session['role']): Session {
  return sessionFor(TENANTS.A, role, { services: ['svc-1'], sub: 'user-1', backendToken: 'backend-token-sample-value' });
}

async function request(
  method: string,
  opts: { role?: Session['role'] | null; csrfHeader?: string; csrfCookie?: string } = {},
) {
  const cookies: Record<string, string> = {};
  if (opts.role !== null) cookies[SESSION_COOKIE] = await sealSession(sample(opts.role ?? 'advisor'));
  cookies[CSRF_COOKIE] = opts.csrfCookie ?? TOKEN;
  const headers = new Headers({ Host: TENANTS.A.host });
  if (opts.csrfHeader !== undefined) headers.set(CSRF_HEADER, opts.csrfHeader);
  return requestWithCookies(URL_, cookies, { method, headers });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('withBff', () => {
  it('answers 401 no-session when there is no session, and does not call the handler', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const response = await withBff(handler)(await request('GET', { role: null }), undefined);
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
    expect(handler).not.toHaveBeenCalled();
  });

  it('answers 403 forbidden when the role is not allowed', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const wrapped = withBff(handler, { roles: ['lead'] });
    const response = await wrapped(await request('GET', { role: 'advisor' }), undefined);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'forbidden' });
    expect(handler).not.toHaveBeenCalled();
  });

  it('calls the handler when the role is allowed', async () => {
    const handler = vi.fn((_r: Request, s: Session) => Response.json({ role: s.role }));
    const wrapped = withBff(handler, { roles: ['lead', 'owner'] });
    const response = await wrapped(await request('GET', { role: 'owner' }), undefined);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ role: 'owner' });
  });

  it('allows any role when no roles are given', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const response = await withBff(handler)(await request('GET', { role: 'wall' }), undefined);
    expect(response.status).toBe(200);
  });

  it('refuses every role when roles is an empty list', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const response = await withBff(handler, { roles: [] })(await request('GET'), undefined);
    expect(response.status).toBe(403);
    expect(handler).not.toHaveBeenCalled();
  });

  it('answers 403 csrf for a POST without the header, and does not call the handler', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const wrapped = withBff(handler, { csrf: true });
    const response = await wrapped(await request('POST'), undefined);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'csrf' });
    expect(handler).not.toHaveBeenCalled();
  });

  it('runs the handler for a POST with a matching header', async () => {
    const handler = vi.fn(() => new Response('done', { status: 201 }));
    const wrapped = withBff(handler, { csrf: true });
    const response = await wrapped(await request('POST', { csrfHeader: TOKEN }), undefined);
    expect(response.status).toBe(201);
    expect(handler).toHaveBeenCalledOnce();
  });

  it.each(['POST', 'PUT', 'PATCH', 'DELETE'])('checks CSRF on %s by default', async (method) => {
    const handler = vi.fn(() => new Response('ok'));
    const wrapped = withBff(handler);
    const refused = await wrapped(await request(method), undefined);
    expect(refused.status).toBe(403);
    expect(await refused.json()).toEqual({ code: 'csrf' });
    const passed = await wrapped(await request(method, { csrfHeader: TOKEN }), undefined);
    expect(passed.status).toBe(200);
  });

  it.each(['GET', 'HEAD'])('does not check CSRF on %s unless asked', async (method) => {
    const handler = vi.fn(() => new Response('ok'));
    expect((await withBff(handler)(await request(method), undefined)).status).toBe(200);
    const strict = await withBff(handler, { csrf: true })(await request(method), undefined);
    expect(strict.status).toBe(403);
  });

  it('still checks CSRF on a POST when csrf is false (an unsafe method cannot opt out)', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const wrapped = withBff(handler, { csrf: false });
    const response = await wrapped(await request('POST'), undefined);
    expect(response.status).toBe(403);
  });

  it('checks the session before the role and the role before CSRF', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const wrapped = withBff(handler, { roles: ['lead'], csrf: true });
    const noSession = await wrapped(await request('POST', { role: null }), undefined);
    expect(noSession.status).toBe(401);
    const wrongRole = await wrapped(await request('POST', { role: 'advisor' }), undefined);
    expect(await wrongRole.json()).toEqual({ code: 'forbidden' });
    const noCsrf = await wrapped(await request('POST', { role: 'lead' }), undefined);
    expect(await noCsrf.json()).toEqual({ code: 'csrf' });
  });

  it('passes the request, the session and the context to the handler', async () => {
    const handler = vi.fn(() => new Response('ok'));
    const req = await request('GET');
    await withBff<{ params: string }>(handler)(req, { params: 'p' });
    expect(handler).toHaveBeenCalledWith(req, expect.objectContaining({ role: 'advisor' }), {
      params: 'p',
    });
  });

  it('turns a thrown FhirError into toBffError', async () => {
    const wrapped = withBff(() => {
      throw new FhirError(404, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] });
    });
    const response = await wrapped(await request('GET'), undefined);
    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ code: 'not-found' });
  });

  it('turns a rejected promise into a 500 without the error text', async () => {
    const spies = (['log', 'info', 'warn', 'error'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const wrapped = withBff(async () => {
      throw new Error('secret detail DT4 8XX');
    });
    const response = await wrapped(await request('GET'), undefined);
    expect(response.status).toBe(500);
    const text = await response.text();
    expect(text).not.toContain('secret detail');
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  it.each(['', 'short'])('answers 500, not 401, for a request with no cookie when SESSION_SECRET is %j', async (value) => {
    vi.stubEnv('SESSION_SECRET', value);
    const handler = vi.fn(() => new Response('ok'));
    const response = await withBff(handler)(new Request(`https://${TENANTS.A.host}/api/bff/x`), undefined);
    expect(response.status).toBe(500);
    expect(handler).not.toHaveBeenCalled();
  });

  it('sends Cache-Control no-store on a thrown-error response', async () => {
    const wrapped = withBff(() => {
      throw new FhirError(404, { resourceType: 'OperationOutcome', issue: [] });
    });
    const response = await wrapped(await request('GET'), undefined);
    expect(response.headers.get('Cache-Control')).toBe('private, no-store');
  });

  it('answers 500 when SESSION_SECRET is missing, never a pass', async () => {
    const req = await request('GET');
    vi.stubEnv('SESSION_SECRET', '');
    const handler = vi.fn(() => new Response('ok'));
    const response = await withBff(handler)(req, undefined);
    expect(response.status).toBe(500);
    expect(handler).not.toHaveBeenCalled();
  });

  it('never puts the back-end token in an error body', async () => {
    const wrapped = withBff((_r, session) => {
      throw new Error(session.backendToken);
    });
    const response = await wrapped(await request('GET'), undefined);
    expect(await response.text()).not.toContain('backend-token-sample-value');
  });
});


describe('every response is private and never stored (TEN-044)', () => {
  const noStore = (response: Response) => {
    const control = (response.headers.get('Cache-Control') ?? '').split(',').map((d) => d.trim().toLowerCase());
    expect(control).toContain('private');
    expect(control).toContain('no-store');
    const vary = (response.headers.get('Vary') ?? '').split(',').map((d) => d.trim().toLowerCase());
    expect(vary).toContain('cookie');
    expect(vary).toContain('host');
  };

  it('on a success the handler made', async () => {
    noStore(await withBff(() => Response.json({ ok: true }))(await request('GET'), undefined));
  });

  it('on a 204 with no body', async () => {
    const response = await withBff(() => new Response(null, { status: 204 }))(await request('GET'), undefined);
    expect(response.status).toBe(204);
    noStore(response);
  });

  it('on every refusal: no session, wrong role, no CSRF, bad input, a thrown error', async () => {
    const wrapped = withBff(() => Response.json({}), { roles: ['lead'] });
    noStore(await wrapped(await request('GET', { role: null }), undefined));
    noStore(await wrapped(await request('GET', { role: 'advisor' }), undefined));
    noStore(await wrapped(await request('POST', { role: 'lead' }), undefined));
    noStore(await withBff(() => Response.json({}))(await requestAs(TENANTS.A, 'advisor', { path: '/api/bff/x?tenant=trust-b' }), undefined));
    noStore(await withBff(() => { throw new Error('x'); })(await request('GET'), undefined));
  });

  it('keeps what the handler set and adds to it: a stream route keeps its no-transform', async () => {
    const response = await withBff(
      () => new Response('data', { headers: { 'Cache-Control': 'no-store, no-transform', 'Content-Type': 'text/event-stream', Vary: 'Accept-Encoding' } }),
    )(await request('GET'), undefined);
    const control = response.headers.get('Cache-Control') ?? '';
    expect(control).toContain('no-transform');
    noStore(response);
    expect(response.headers.get('Vary')).toContain('Accept-Encoding');
    expect(response.headers.get('Content-Type')).toBe('text/event-stream');
  });

  it('takes away a public or max-age directive the handler set', async () => {
    const response = await withBff(() => new Response('x', { headers: { 'Cache-Control': 'public, max-age=3600, s-maxage=60' } }))(
      await request('GET'),
      undefined,
    );
    const control = response.headers.get('Cache-Control') ?? '';
    expect(control).not.toMatch(/public|max-age|s-maxage/);
    noStore(response);
  });

  it('works on a response whose headers cannot be changed (one made by fetch)', async () => {
    const immutable = Response.error();
    expect(() => immutable.headers.set('X', 'y')).toThrow();
    const response = await withBff(() => Response.redirect('https://example.test/', 302))(await request('GET'), undefined);
    expect(response.status).toBe(302);
    noStore(response);
  });

  it('keeps the status, the status text and the body', async () => {
    const response = await withBff(() => new Response('hello', { status: 201, statusText: 'Created' }))(await request('GET'), undefined);
    expect(response.status).toBe(201);
    expect(await response.text()).toBe('hello');
  });
});

describe('inputs that name a tenant, a scope or a network are refused (TEN-044)', () => {
  const handler = () => vi.fn(() => Response.json({ reached: true }));

  async function refused(request: Request) {
    const inner = handler();
    const response = await withBff(inner)(request, undefined);
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: 'invalid' });
    expect(inner).not.toHaveBeenCalled();
    return response;
  }

  it.each([
    'tenant',
    'tenantId',
    'tenant_id',
    'tenant-id',
    'TENANT',
    'scope',
    'network',
    'networkId',
    'source',
    'sourceTenantId',
    'tenant.id',
    'tenant[id]',
  ])('refuses the query parameter %s', async (name) => {
    await refused(await requestAs(TENANTS.A, 'advisor', { path: `/api/bff/x?${encodeURIComponent(name)}=${TENANTS.B.id}` }));
  });

  it.each(['X-Tenant-Id', 'x-tenant', 'X-Tenant-Host', 'X-Scope', 'X-Network', 'X-Network-Id', 'X-Source-Tenant', 'Tenant'])(
    'refuses the header %s',
    async (name) => {
      await refused(await requestAs(TENANTS.A, 'advisor', { headers: { [name]: TENANTS.B.id } }));
    },
  );

  it.each([
    ['tenantId at the top', { tenantId: 'trust-b' }],
    ['scope at the top', { scope: 'network' }],
    ['network at the top', { network: 'net-x' }],
    ['a tenant deep in the body', { a: { b: [{ c: { tenant: 'trust-b' } }] } }],
    ['sourceTenantId in a list', { rows: [{ sourceTenantId: 'trust-b' }] }],
  ])('refuses a JSON body with %s', async (_name, body) => {
    await refused(
      await requestAs(TENANTS.A, 'advisor', {
        method: 'POST',
        csrf: TOKEN,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    );
  });

  it('refuses a form body that names a tenant', async () => {
    await refused(
      await requestAs(TENANTS.A, 'advisor', {
        method: 'POST',
        csrf: TOKEN,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'next=%2Flead&tenant=trust-b',
      }),
    );
  });

  it('refuses a JSON body nested too deep to check, and one too large to check', async () => {
    let deep: unknown = { x: 1 };
    for (let i = 0; i < 30; i += 1) deep = { n: deep };
    await refused(
      await requestAs(TENANTS.A, 'advisor', { method: 'POST', csrf: TOKEN, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(deep) }),
    );
    await refused(
      await requestAs(TENANTS.A, 'advisor', {
        method: 'POST',
        csrf: TOKEN,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: 'x'.repeat(300_000) }),
      }),
    );
  });

  it('lets a request through that names none of them, and the handler can still read its body', async () => {
    const inner = vi.fn(async (req: Request) => Response.json(await req.json()));
    const response = await withBff(inner)(
      await requestAs(TENANTS.A, 'advisor', {
        method: 'POST',
        csrf: TOKEN,
        path: '/api/bff/x?page=2&filter=late',
        headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'abc' },
        body: JSON.stringify({ value: 4, note: 'tenanted is not a tenant key' }),
      }),
      undefined,
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ value: 4, note: 'tenanted is not a tenant key' });
  });

  it('does not refuse a key that only contains the word, such as a service called "network-nurse"', async () => {
    const inner = handler();
    const response = await withBff(inner)(await requestAs(TENANTS.A, 'advisor', { path: '/api/bff/x?q=network&name=scoped' }), undefined);
    expect(response.status).toBe(200);
  });

  it('asks the session first: a caller with no session is told 401 whatever they sent', async () => {
    const response = await withBff(handler())(
      new Request(`${URL_}?tenant=trust-b`, { headers: { Host: TENANTS.A.host } }),
      undefined,
    );
    expect(response.status).toBe(401);
  });
});

describe('the session is for this host (TEN-044)', () => {
  it('answers 401 when a session made for tenant A arrives addressed to tenant B', async () => {
    const inner = vi.fn(() => Response.json({}));
    const response = await withBff(inner)(await requestAs(TENANTS.A, 'advisor', { host: TENANTS.B.host }), undefined);
    expect(response.status).toBe(401);
    expect(inner).not.toHaveBeenCalled();
  });

  it('hands the handler the tenant of the session and nothing from the request', async () => {
    const inner = vi.fn((_r: Request, s: Session) => Response.json({ tenantId: s.tenantId }));
    const response = await withBff(inner)(await requestAs(TENANTS.B, 'advisor'), undefined);
    expect(await response.json()).toEqual({ tenantId: TENANTS.B.id });
  });
});

describe('a back end that ends the session ends it here too (TEN-044)', () => {
  it('turns a 401 from the back end into a 401 and clears the session and CSRF cookies', async () => {
    const wrapped = withBff(() => {
      throw new FhirError(401, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] });
    });
    const response = await wrapped(await request('GET'), undefined);
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
    for (const name of [SESSION_COOKIE, CSRF_COOKIE]) {
      expect(lastWrite(name)?.options.maxAge).toBe(0);
    }
  });

  it.each([400, 403, 404, 409, 500, 503])('leaves the session alone for a %s from the back end', async (status) => {
    const wrapped = withBff(() => {
      throw new FhirError(status, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] });
    });
    await wrapped(await request('GET'), undefined);
    expect(cookieWrites.filter((w) => w.name === SESSION_COOKIE)).toHaveLength(0);
  });
});

describe('an id that is not in this tenant looks like an id that is nowhere (TEN-044)', () => {
  const outcome = (code: string) => ({ resourceType: 'OperationOutcome' as const, issue: [{ severity: 'error' as const, code }] });

  it.each([
    ['not found', 404, 'not-found'],
    ['forbidden', 403, 'forbidden'],
    ['security', 403, 'security'],
  ])('answers the one 404 for a %s from the back end on an id route', async (_name, status, code) => {
    const wrapped = withBff(
      () => {
        throw new FhirError(status, outcome(code));
      },
      { idScoped: true },
    );
    const response = await wrapped(await request('GET'), undefined);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('gives the same bytes for an id that does not exist and one that belongs to another tenant', async () => {
    const make = (status: number, code: string) =>
      withBff(
        () => {
          throw new FhirError(status, outcome(code));
        },
        { idScoped: true },
      );
    const absent = await make(404, 'not-found')(await request('GET'), undefined);
    const other = await make(403, 'forbidden')(await request('GET'), undefined);
    expect(await other.text()).toBe(await absent.text());
    expect(other.status).toBe(absent.status);
  });

  it('keeps a 403 as a 403 on a route that is not id-scoped', async () => {
    const wrapped = withBff(() => {
      throw new FhirError(403, outcome('forbidden'));
    });
    expect((await wrapped(await request('GET'), undefined)).status).toBe(403);
  });
});

describe('the CSRF token is the session’s own (TEN-046)', () => {
  const run = async (csrf: string) => {
    const handler = vi.fn(() => new Response('done'));
    const response = await withBff(handler)(await requestAs(TENANTS.A, 'advisor', { method: 'POST', csrf }), undefined);
    return { response, handler };
  };

  it('runs the handler for the token issued to the session', async () => {
    const { response, handler } = await run(TOKEN);
    expect(response.status).toBe(200);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('answers 403 csrf for a matching cookie and header that were issued to another tenant’s session', async () => {
    const forB = csrfFor(sessionFor(TENANTS.B, 'advisor'));
    const { response, handler } = await run(forB);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'csrf' });
    expect(handler).not.toHaveBeenCalled();
  });

  it('answers 403 csrf for a planted matching pair of the old unbound shape', async () => {
    const { response, handler } = await run('A'.repeat(43));
    expect(response.status).toBe(403);
    expect(handler).not.toHaveBeenCalled();
  });

  it('answers 403 csrf for a token issued to another person of the same tenant', async () => {
    const { response } = await run(csrfFor(sessionFor(TENANTS.A, 'advisor', { sub: 'stf-another-person' })));
    expect(response.status).toBe(403);
  });
});
