// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { withBff } from './handler';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const TOKEN = 'A'.repeat(43);
const URL_ = 'https://app.test/api/bff/thing';

function sample(role: Session['role']): Session {
  return {
    role,
    services: ['svc-1'],
    sub: 'user-1',
    backendToken: 'backend-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function request(
  method: string,
  opts: { role?: Session['role'] | null; csrfHeader?: string; csrfCookie?: string } = {},
) {
  const cookies: Record<string, string> = {};
  if (opts.role !== null) cookies[SESSION_COOKIE] = await sealSession(sample(opts.role ?? 'advisor'));
  cookies[CSRF_COOKIE] = opts.csrfCookie ?? TOKEN;
  const headers = new Headers();
  if (opts.csrfHeader !== undefined) headers.set(CSRF_HEADER, opts.csrfHeader);
  return requestWithCookies(URL_, cookies, { method, headers });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
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
    const response = await withBff(handler)(new Request('http://localhost/api/bff/x'), undefined);
    expect(response.status).toBe(500);
    expect(handler).not.toHaveBeenCalled();
  });

  it('sends Cache-Control no-store on a thrown-error response', async () => {
    const wrapped = withBff(() => {
      throw new FhirError(404, { resourceType: 'OperationOutcome', issue: [] });
    });
    const response = await wrapped(await request('GET'), undefined);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
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
