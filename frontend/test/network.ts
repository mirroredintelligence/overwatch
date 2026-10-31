import type { Role } from '@/lib/auth/session';
import { requestAs } from '@/test/requests';
import type { TestTenant } from '@/test/tenants';

// A request to a network BFF route, as a signed-in person of a tenant would send it. The network
// is named by the one query key the network routes allow (`networkId`) and nothing else.

export const NETWORK_ID = 'net-sample';

export async function networkRequest(
  tenant: TestTenant,
  role: Role,
  route: string,
  query: Record<string, string> | string = { networkId: NETWORK_ID },
): Promise<Request> {
  const search = typeof query === 'string' ? query : new URLSearchParams(query).toString();
  return requestAs(tenant, role, { path: `/api/bff/network${route}${search === '' ? '' : `?${search}`}` });
}
