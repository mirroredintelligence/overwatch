// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE } from '@/lib/auth/session';
import { cookieWrites, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { OPERATOR_HOST, requestAsOperator } from '@/test/operator';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { withOperatorBff } from './bff';
import { OPERATOR_COOKIE } from './session';
import { fhirFetch } from '@/lib/fhir/client';

// The wrapper of the operator's BFF routes (TEN-083), like `withBff` for a tenant's person: the operator's
// session, its role, CSRF and the input guard first, then the handler, every answer private and never stored.
// An operator session is not a tenant session and neither is let in by the other's wrapper.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');

const ok = async (_request: Request, session: { role: string }) => Response.json({ role: session.role });
const get = withOperatorBff(ok);
const post = withOperatorBff(ok, { roles: ['platform-operator'] });
const supportOnly = withOperatorBff(ok, { roles: ['support'] });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
});
afterEach(() => vi.unstubAllEnvs());

describe('withOperatorBff', () => {
  it('answers 401 no-session, private and not stored, to a request with no session', async () => {
    const response = await get(new Request(`https://${OPERATOR_HOST}/x`, { headers: { Host: OPERATOR_HOST } }), undefined);
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(response.headers.get('cache-control')).toContain('private');
    expect(response.headers.get('vary')).toMatch(/Cookie/);
  });

  it('lets in an operator and a support person, and hands the handler the session', async () => {
    for (const role of ['platform-operator', 'support'] as const) {
      const response = await get(await requestAsOperator(role), undefined);
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ role });
    }
  });

  it('answers a tenant session of every tenant role exactly as no session: a tenant person is not an operator', async () => {
    const none = await get(new Request(`https://${OPERATOR_HOST}/x`, { headers: { Host: OPERATOR_HOST } }), undefined);
    const noneText = await none.text();
    for (const role of ['advisor', 'clinical', 'lead', 'owner', 'exec', 'support', 'audit', 'tenant-admin', 'network-admin'] as const) {
      const request = await requestAs(TENANTS.A, role);
      const crossed = await get(request, undefined);
      expect(crossed.status, role).toBe(401);
      expect(await crossed.text(), role).toBe(noneText);
    }
  });

  it('answers a tenant session cookie renamed to the operator one as no session', async () => {
    const tenant = await requestAs(TENANTS.A, 'tenant-admin');
    const sealed = /diucs_session=([^;]+)/.exec(tenant.headers.get('cookie') ?? '')?.[1] ?? '';
    const forged = requestWithCookies(`https://${TENANTS.A.host}/x`, { [OPERATOR_COOKIE]: sealed }, { headers: { Host: TENANTS.A.host } });
    expect((await get(forged, undefined)).status).toBe(401);
  });

  it('answers an operator session sent to another host as no session', async () => {
    const response = await get(await requestAsOperator('platform-operator', { host: TENANTS.A.host }), undefined);
    expect(response.status).toBe(401);
  });

  it('answers 403 forbidden to a role the route is not for, and never runs the handler', async () => {
    const handler = vi.fn(ok);
    const route = withOperatorBff(handler, { roles: ['platform-operator'] });
    const response = await route(await requestAsOperator('support'), undefined);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'forbidden' });
    expect(handler).not.toHaveBeenCalled();
    expect((await supportOnly(await requestAsOperator('platform-operator'), undefined)).status).toBe(403);
  });

  it('needs the operator’s CSRF token for POST, PUT and DELETE, and none for a GET', async () => {
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      const none = await post(await requestAsOperator('platform-operator', { method }), undefined);
      expect(none.status, method).toBe(403);
      expect(await none.json()).toEqual({ code: 'csrf' });
      expect((await post(await requestAsOperator('platform-operator', { method, csrf: 'x'.repeat(87) }), undefined)).status, method).toBe(403);
      expect((await post(await requestAsOperator('platform-operator', { method, csrf: true }), undefined)).status, method).toBe(200);
    }
    expect((await post(await requestAsOperator('platform-operator'), undefined)).status).toBe(200);
  });

  it('does not take a tenant’s CSRF pair: the token of a tenant session is no operator token', async () => {
    const tenant = await requestAs(TENANTS.A, 'tenant-admin', { csrf: true });
    const token = tenant.headers.get('x-csrf-token') ?? '';
    const response = await post(await requestAsOperator('platform-operator', { method: 'POST', headers: { 'X-CSRF-Token': token }, cookies: { diucs_csrf: token } }), undefined);
    expect(response.status).toBe(403);
  });

  it('refuses, with 400, a request that names a tenant, a scope or a network in the query, a header or a body', async () => {
    for (const query of ['tenant=trust-b', 'scope=network', 'networkId=net-sample']) {
      const response = await get(await requestAsOperator('platform-operator', { path: `/api/bff/x?${query}` }), undefined);
      expect(response.status, query).toBe(400);
      expect(await response.json()).toEqual({ code: 'invalid' });
    }
    expect((await get(await requestAsOperator('platform-operator', { headers: { 'X-Tenant-Id': 'trust-b' } }), undefined)).status).toBe(400);
    const body = await post(
      await requestAsOperator('platform-operator', { method: 'POST', csrf: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenantId: 'trust-b' }) }),
      undefined,
    );
    expect(body.status).toBe(400);
  });

  it('ends the session and answers 401 session-ended when the back end no longer knows the token', async () => {
    server.use(http.get(`${ROOT}/platform/session`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login', diagnostics: 'x' }] }, { status: 401 })));
    const route = withOperatorBff(async (_request, session) => {
      await fhirFetch('/platform/session', { root: true, token: session.backendToken });
      return Response.json({});
    });
    const response = await route(await requestAsOperator('platform-operator'), undefined);
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
    const names = cookieWrites.map((w) => w.name);
    expect(names).toContain(OPERATOR_COOKIE);
    expect(names).not.toContain(SESSION_COOKIE);
  });

  it('turns a failure into a fixed answer and, on a route that takes an id, a 403 into the one 404', async () => {
    const boom = withOperatorBff(async () => {
      throw new Error('detail that must not leak: trust-b');
    });
    const response = await boom(await requestAsOperator('platform-operator'), undefined);
    expect(response.status).toBe(500);
    expect(await response.text()).not.toMatch(/trust-b|detail/);

    server.use(http.get(`${ROOT}/platform/tenants/trust-a`, () => HttpResponse.json({}, { status: 403 })));
    const scoped = withOperatorBff(
      async (_request, session) => {
        await fhirFetch('/platform/tenants/trust-a', { root: true, token: session.backendToken });
        return Response.json({});
      },
      { idScoped: true },
    );
    expect((await scoped(await requestAsOperator('platform-operator'), undefined)).status).toBe(404);
  });
});
