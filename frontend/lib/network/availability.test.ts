// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { FhirError } from '@/lib/fhir/client';
import { sessionFor } from '@/test/requests';
import { NETWORK_ROOT, networkHandlers, resetNetworkBackend, seenNetwork } from '@/test/msw/handlers/network';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { offeredNetworks, requireOffered } from './availability';

// TEN-068: the availability check, made on every call. A page asks for a network by the id the server
// offered; the BFF asks the back end which networks THIS session's tenant may see now (the registry, not
// the token's claim) and lets the call through only for one of them. A tenant that is not a member, a
// member that left, an unknown network and a role that never sees one are the same 404, and the
// network's own routes are not called at all for them.

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${NETWORK_ROOT}/fhir`);
  resetNetworkBackend();
  server.use(...networkHandlers);
});
afterEach(() => vi.unstubAllEnvs());

const A = () => sessionFor(TENANTS.A, 'advisor');
const C = () => sessionFor(TENANTS.C, 'advisor');
const networkCalls = () => seenNetwork.filter((call) => call.path.startsWith('/network/'));

describe('offeredNetworks', () => {
  it('lists the networks of the back end for this session, from the root', async () => {
    const list = await offeredNetworks(A());
    expect(list.map((n) => n.id)).toEqual(['net-sample']);
    expect(seenNetwork.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /networks']);
    expect(seenNetwork[0]?.query).toBe('');
  });

  it('lists none for a tenant that is in no network', async () => {
    expect(await offeredNetworks(C())).toEqual([]);
  });

  it('passes a refusal of the back end on (a role that never sees a network is 404)', async () => {
    await expect(offeredNetworks(sessionFor(TENANTS.A, 'wall'))).rejects.toMatchObject({ status: 404 });
  });

  it('passes a back end that is down on as 503, never as an empty list', async () => {
    server.use(http.get(`${NETWORK_ROOT}/networks`, () => HttpResponse.json({}, { status: 503 })));
    await expect(offeredNetworks(A())).rejects.toMatchObject({ status: 503 });
  });

  it('refuses an answer that is not a list of networks with a 502', async () => {
    server.use(http.get(`${NETWORK_ROOT}/networks`, () => HttpResponse.json({ networks: [{ id: 'trust-a' }] })));
    await expect(offeredNetworks(A())).rejects.toMatchObject({ status: 502 });
  });
});

describe('requireOffered', () => {
  it('gives the network when it is one the session may see', async () => {
    expect(await requireOffered(A(), 'net-sample')).toMatchObject({ id: 'net-sample', name: 'Sample Network' });
  });

  it('is a 404 for a network that is not offered, with no call to the network routes', async () => {
    const error = await requireOffered(A(), 'net-other').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(FhirError);
    expect(error).toMatchObject({ status: 404 });
    expect(networkCalls()).toEqual([]);
  });

  it('is the same 404 for a tenant that is in no network, with no call to the network routes', async () => {
    const unknown = (await requireOffered(A(), 'net-other').catch((e: unknown) => e)) as FhirError;
    const nonMember = (await requireOffered(C(), 'net-sample').catch((e: unknown) => e)) as FhirError;
    expect(nonMember).toMatchObject({ status: 404 });
    expect(nonMember.outcome).toEqual(unknown.outcome);
    expect(networkCalls()).toEqual([]);
  });

  it('asks again on every call: a member that left between two calls is refused on the second', async () => {
    expect(await requireOffered(A(), 'net-sample')).toBeDefined();
    server.use(http.get(`${NETWORK_ROOT}/networks`, () => HttpResponse.json({ networks: [] })));
    await expect(requireOffered(A(), 'net-sample')).rejects.toMatchObject({ status: 404 });
  });
});
