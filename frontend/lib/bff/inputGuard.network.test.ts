// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { withBff } from './handler';

// TEN-068: the input guard refuses every field whose name starts with `network`. A route that needs the
// id of the network a page is looking at says so (`allowNetworkId`), and then ONLY a `networkId` query
// key, once, holding a network id, is let through. Nothing else changes: not a header, not a body, not
// another key, not a tenant or a scope, and every route that does not say so refuses it as before.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => vi.unstubAllEnvs());

const inner = () => vi.fn((request: Request) => Response.json({ asked: new URL(request.url).searchParams.get('networkId') }));

async function ask(query: string, options: { allow: boolean; headers?: Record<string, string> }) {
  const handler = inner();
  const wrapped = withBff(handler, options.allow ? { allowNetworkId: true } : {});
  const response = await wrapped(await requestAs(TENANTS.A, 'advisor', { path: `/api/bff/x${query}`, headers: options.headers }), undefined);
  return { response, handler };
}

describe('allowNetworkId', () => {
  it('lets a networkId through on a route that allows it, and the handler reads it', async () => {
    const { response, handler } = await ask('?networkId=net-sample', { allow: true });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ asked: 'net-sample' });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('still refuses it on a route that does not allow it', async () => {
    const { response, handler } = await ask('?networkId=net-sample', { allow: false });
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: 'invalid' });
    expect(handler).not.toHaveBeenCalled();
  });

  it.each(['tenant=trust-b', 'tenantId=trust-b', 'scope=network', 'network=net-sample', 'networkIds=net-sample', 'network_id=net-sample', 'sourceTenantId=trust-b', 'source=x'])(
    'still refuses %s on a route that allows networkId',
    async (query) => {
      const { response, handler } = await ask(`?networkId=net-sample&${query}`, { allow: true });
      expect(response.status).toBe(400);
      expect(handler).not.toHaveBeenCalled();
    },
  );

  it.each(['networkId=', 'networkId=trust-b', 'networkId=NET-SAMPLE', 'networkId=net-', 'networkId=net-x%20y', `networkId=net-${'a'.repeat(40)}`, 'networkId=net-sample&networkId=net-other'])(
    'refuses %s: a value that is not a network id, or a second one',
    async (query) => {
      const { response, handler } = await ask(`?${query}`, { allow: true });
      expect(response.status).toBe(400);
      expect(handler).not.toHaveBeenCalled();
    },
  );

  it('lets a request through with no networkId at all', async () => {
    const { response } = await ask('', { allow: true });
    expect(response.status).toBe(200);
  });

  it('never lets a header name a network, a tenant or a scope', async () => {
    for (const name of ['X-Network-Id', 'X-Network', 'X-Tenant-Id', 'X-Scope']) {
      const { response, handler } = await ask('?networkId=net-sample', { allow: true, headers: { [name]: 'net-sample' } });
      expect(response.status, name).toBe(400);
      expect(handler).not.toHaveBeenCalled();
    }
  });

  it('never lets a JSON body name a network', async () => {
    const handler = inner();
    const response = await withBff(handler, { allowNetworkId: true })(
      await requestAs(TENANTS.A, 'advisor', {
        method: 'POST',
        csrf: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ networkId: 'net-sample' }),
      }),
      undefined,
    );
    expect(response.status).toBe(400);
    expect(handler).not.toHaveBeenCalled();
  });
});
