// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES, type Role } from '@/lib/auth/session';
import { OPTIONS_BODY } from '@/test/fixtures/network';
import { NETWORK_ID, networkRequest } from '@/test/network';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { NETWORK_ROOT, networkHandlers, resetNetworkBackend, seenNetwork } from '@/test/msw/handlers/network';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

// WB11: GET /api/bff/network/options?networkId=&case=. The other organisations' services that may take the
// advisor's case, read only. The network is the `networkId` the server offered (checked against the registry
// on every call), the case is the advisor's own case reference, the back end reads the case in the advisor's
// own tenant, and the answer is rebuilt from the fields the page uses.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${NETWORK_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetNetworkBackend();
  server.use(...networkHandlers);
});
afterEach(() => vi.unstubAllEnvs());

const A = TENANTS.A;
const ask = (role: Role, query: Record<string, string> | string = { networkId: NETWORK_ID, case: 'case-1001' }) =>
  networkRequest(A, role, '/options', query);
const optionCalls = () => seenNetwork.filter((c) => c.path.endsWith('/options'));

describe('GET /api/bff/network/options', () => {
  it('answers the options in camelCase, with the organisation of each row, and nothing the page does not use', async () => {
    const response = await GET(await ask('advisor'));
    expect(response.status).toBe(200);
    const body = (await response.json()) as { options: Record<string, unknown>[]; notSuitable: Record<string, unknown>[]; patient: unknown };
    expect(body.options.map((o) => o.rowRef)).toEqual(['lst-0002', 'lst-0005']);
    expect(body.options[0]).toMatchObject({ organisationName: 'Sample Area B', status: 'limited', contactPhone: '01632 960010', travel: { lowMinutes: 12, highMinutes: 24 } });
    expect(body.notSuitable.map((o) => o.reason)).toEqual(['not updated for 4 hrs. Phone to confirm.', 'not available on the network. Phone to confirm.']);
    expect(body.patient).toEqual({ lat: 50.6, lon: -2.4 });
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('asks the registry first, then the back end for the one network with the case reference, with the advisor’s token', async () => {
    await GET(await ask('advisor'));
    expect(seenNetwork.map((c) => c.path)).toEqual(['/networks', `/network/${NETWORK_ID}/options`]);
    expect(optionCalls()[0]).toMatchObject({ method: 'GET', query: 'case=case-1001', authorised: true });
  });

  it('lets the advisor and the clinician in, and refuses every other role with the one 404 and no read of the network', async () => {
    for (const role of ROLES) {
      seenNetwork.length = 0;
      const response = await GET(await ask(role));
      if (role === 'advisor' || role === 'clinical') {
        expect(response.status, role).toBe(200);
      } else {
        expect([401, 403], role).toContain(response.status);
        expect(optionCalls(), role).toHaveLength(0);
      }
    }
  });

  it('is 401 with no session', async () => {
    const response = await GET(new Request(`https://${A.host}/api/bff/network/options?networkId=${NETWORK_ID}&case=c1`, { headers: { Host: A.host } }));
    expect(response.status).toBe(401);
  });

  it('answers a network the tenant is not offered, and a network id that is not one, without asking for the options', async () => {
    const unknown = await GET(await ask('advisor', { networkId: 'net-unknown', case: 'case-1001' }));
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
    const bad = await GET(await ask('advisor', { networkId: 'trust-b', case: 'case-1001' }));
    expect(bad.status).toBe(400);
    expect(optionCalls()).toHaveLength(0);
  });

  it.each([
    ['no case', { networkId: NETWORK_ID }],
    ['a case that is not a reference', { networkId: NETWORK_ID, case: '../x' }],
    ['a case that is too long', { networkId: NETWORK_ID, case: 'c'.repeat(65) }],
    ['two cases', 'networkId=net-sample&case=a&case=b'],
    ['another key', { networkId: NETWORK_ID, case: 'case-1001', postcode: 'DT4 8XX' }],
    ['a tenant', { networkId: NETWORK_ID, case: 'case-1001', tenantId: 'x' }],
    ['a scope', { networkId: NETWORK_ID, case: 'case-1001', scope: 'network' }],
  ])('refuses %s (400) before it asks the back end for the options', async (_name, query) => {
    const response = await GET(await ask('advisor', query));
    expect(response.status).toBe(400);
    expect(optionCalls()).toHaveLength(0);
  });

  it('keeps the back end’s refusal of the case as the one 404, a closed case and an incomplete one as they are', async () => {
    for (const [status, expected] of [[404, 404], [409, 409], [400, 400], [503, 503]] as const) {
      server.use(http.get(`${NETWORK_ROOT}/network/:id/options`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'x', diagnostics: 'y' }] }, { status })));
      expect((await GET(await ask('advisor'))).status).toBe(expected);
    }
  });

  it('answers 502, never a guess, when the back end sends options it cannot read', async () => {
    server.use(http.get(`${NETWORK_ROOT}/network/:id/options`, () => HttpResponse.json({ ...OPTIONS_BODY, options: [{ ...OPTIONS_BODY.options[0], status: 'busy' }] })));
    expect((await GET(await ask('advisor'))).status).toBe(502);
  });

  it('never passes on a tenant, a grant or a source id the back end sent by mistake', async () => {
    server.use(http.get(`${NETWORK_ROOT}/network/:id/options`, () => HttpResponse.json({ ...OPTIONS_BODY, tenant_id: 'tenant-b', options: [{ ...OPTIONS_BODY.options[0], source_tenant_id: 'tenant-b', grant_id: 'g-1' }] })));
    const text = await (await GET(await ask('advisor'))).text();
    expect(text).not.toMatch(/tenant-b|grant|g-1|source/);
  });
});
