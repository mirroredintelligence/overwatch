// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';
import { fakeBackendToken } from '@/test/backendToken';
import { canary, inspectUpstream, type Leak } from '@/test/leak-canary';
import { server } from '@/test/msw/server';
import { NETWORK, TENANTS } from '@/test/tenants';

// The leak canary (TEN-047, audit D 7.3) looks at every call the front end makes to the back end, in
// every test, and fails the test that makes a call that could leak a tenant: a token of another tenant
// than the session's, a header, query key or body that names a tenant, a bearer on a link call, a
// network route reached by a tenant that is not a member, a call with no token, a token for another
// audience. These tests make each of those calls and show the canary sees it.

const A = TENANTS.A;
const B = TENANTS.B;
const C = TENANTS.C;
const BACKEND = 'http://backend.test';

function upstream(path: string, init: { token?: string; headers?: Record<string, string>; method?: string } = {}) {
  const headers = new Headers(init.headers);
  if (init.token) headers.set('Authorization', `Bearer ${init.token}`);
  return { method: init.method ?? 'GET', url: `${BACKEND}${path}`, headers };
}
const token = (tenant: string, extra: Record<string, unknown> = {}) => fakeBackendToken({ tenant, ...extra });
const rules = (leaks: Leak[]) => leaks.map((l) => l.rule);

afterEach(() => canary.reset());

describe('inspectUpstream: what is a leak', () => {
  it('is nothing for a call with the session tenant’s token', () => {
    expect(inspectUpstream(upstream('/fhir/HealthcareService/s1', { token: token(A.id) }), new Set([A.id]))).toEqual([]);
  });

  it('is a leak when the token is another tenant’s than the session’s', () => {
    const leaks = inspectUpstream(upstream('/fhir/HealthcareService/s1', { token: token(B.id) }), new Set([A.id]));
    expect(rules(leaks)).toEqual(['tenant-mismatch']);
  });

  it('is not a leak when no tenant is expected yet, or the token is opaque (a test token with no claims)', () => {
    expect(inspectUpstream(upstream('/fhir/x', { token: token(B.id) }), new Set())).toEqual([]);
    expect(inspectUpstream(upstream('/fhir/x', { token: 'token-for-organisation-b' }), new Set([A.id]))).toEqual([]);
  });

  it.each(['X-Tenant-Id', 'x-tenant', 'X-Tenant-Host', 'X-Scope', 'X-Network', 'X-Source-Tenant'])(
    'is a leak when the call carries the header %s',
    (name) => {
      const leaks = inspectUpstream(upstream('/fhir/x', { token: token(A.id), headers: { [name]: B.id } }), new Set([A.id]));
      expect(rules(leaks)).toContain('tenant-header');
    },
  );

  it.each(['tenant', 'tenantId', 'scope', 'network', 'Tenant_ID'])('is a leak when the query names %s', (key) => {
    const leaks = inspectUpstream(upstream(`/fhir/x?${key}=${B.id}`, { token: token(A.id) }), new Set([A.id]));
    expect(rules(leaks)).toContain('tenant-query');
  });

  it('is a leak when a link call carries an Authorization header', () => {
    const leaks = inspectUpstream(upstream('/links/SomeLinkToken', { token: token(A.id) }), new Set([A.id]));
    expect(rules(leaks)).toEqual(['link-bearer']);
  });

  it('is nothing for a link call with no Authorization, and for the calls that have no token by design', () => {
    for (const path of ['/links/SomeLinkToken', '/links/SomeLinkToken/renew', '/auth/token', '/public/tenant-profile']) {
      expect(inspectUpstream(upstream(path, { method: path === '/public/tenant-profile' ? 'GET' : 'POST' }), new Set([A.id]))).toEqual([]);
    }
  });

  it('is a leak when a call to the FHIR API has no token', () => {
    expect(rules(inspectUpstream(upstream('/fhir/HealthcareService/s1'), new Set([A.id])))).toEqual(['no-token']);
  });

  it('is a leak when the token is for another audience (an operator token at the tenant API)', () => {
    const leaks = inspectUpstream(upstream('/fhir/x', { token: token(A.id, { aud: 'diucs-ops' }) }), new Set([A.id]));
    expect(rules(leaks)).toEqual(['bad-audience']);
  });

  it('is a leak when a network route is reached with the token of a tenant that is not a member', () => {
    const outsider = inspectUpstream(upstream(`/network/${NETWORK.id}/board`, { token: token(C.id) }), new Set([C.id]));
    expect(rules(outsider)).toEqual(['network-non-member']);
    for (const member of NETWORK.memberIds) {
      expect(inspectUpstream(upstream(`/network/${NETWORK.id}/board`, { token: token(member) }), new Set([member]))).toEqual([]);
    }
  });

  it('reports several leaks of one call, each with a rule, the method and the path, and never the token', () => {
    const t = token(B.id);
    const leaks = inspectUpstream(upstream('/fhir/x?tenant=a', { token: t, headers: { 'X-Tenant-Id': 'a' } }), new Set([A.id]));
    expect(rules(leaks).sort()).toEqual(['tenant-header', 'tenant-mismatch', 'tenant-query']);
    expect(JSON.stringify(leaks)).not.toContain(t);
    expect(JSON.stringify(leaks)).not.toContain(t.split('.')[1]);
    expect(leaks[0]?.method).toBe('GET');
    expect(leaks[0]?.url).toBe('/fhir/x');
  });

  it('looks only at the back end: a call to another origin is not its business', () => {
    expect(inspectUpstream({ method: 'GET', url: 'https://login.entra-fake.test/organizations/x?tenant=1', headers: new Headers() }, new Set([A.id]))).toEqual([]);
  });
});

describe('the installed canary', () => {
  it('sees a real call the code under test makes, and fails the test that made it', async () => {
    server.use(http.get(`${BACKEND}/fhir/Probe/1`, () => HttpResponse.json({})));
    canary.expect(A.id);
    await fetch(`${BACKEND}/fhir/Probe/1`, { headers: { Authorization: `Bearer ${token(B.id)}` } });
    expect(canary.leaks().map((l) => l.rule)).toEqual(['tenant-mismatch']);
    expect(() => canary.assertClean()).toThrow(/tenant-mismatch/);
    canary.reset();
    expect(() => canary.assertClean()).not.toThrow();
  });

  it('stays quiet for a clean call', async () => {
    server.use(http.get(`${BACKEND}/fhir/Probe/2`, () => HttpResponse.json({})));
    canary.expect(A.id);
    await fetch(`${BACKEND}/fhir/Probe/2`, { headers: { Authorization: `Bearer ${token(A.id)}` } });
    expect(canary.leaks()).toEqual([]);
  });

  it('forgets everything between tests: the expected tenants and the leaks', () => {
    expect(canary.leaks()).toEqual([]);
    expect(canary.expected().size).toBe(0);
  });

  it('puts no token, cookie or host in the message it throws', async () => {
    server.use(http.get(`${BACKEND}/fhir/Probe/3`, () => HttpResponse.json({})));
    canary.expect(A.id);
    const t = token(B.id);
    await fetch(`${BACKEND}/fhir/Probe/3`, { headers: { Authorization: `Bearer ${t}` } });
    let message = '';
    try {
      canary.assertClean();
    } catch (error) {
      message = String((error as Error).message);
    }
    expect(message).not.toContain(t);
    expect(message).not.toContain('Bearer');
    canary.reset();
  });
});
