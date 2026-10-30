import { DIRECTORY_A, DIRECTORY_B } from '@/test/oidc/constants';

// The tenants the front-end tests sign in as. Sample values only: nothing here is a real
// organisation, host or directory. A third tenant has no directory bound, so a test can show that a
// person of tenant A or B gets nothing there. Hosts are one sub-domain per tenant (DEC-134 item 3).

export type TestTenant = {
  readonly id: string;
  readonly host: string;
  readonly displayName: string;
  /** The Entra directory the tenant has bound, or null when it has none. */
  readonly directoryId: string | null;
};

export const TENANT_A_FIXTURE: TestTenant = {
  id: 'trust-a',
  host: 'tenant-a.example.test',
  displayName: 'Sample Area A',
  directoryId: DIRECTORY_A,
};

export const TENANT_B_FIXTURE: TestTenant = {
  id: 'trust-b',
  host: 'tenant-b.example.test',
  displayName: 'Sample Area B',
  directoryId: DIRECTORY_B,
};

export const TENANT_C_FIXTURE: TestTenant = {
  id: 'trust-c',
  host: 'tenant-c.example.test',
  displayName: 'Sample Area C',
  directoryId: null,
};

export const TENANTS = { A: TENANT_A_FIXTURE, B: TENANT_B_FIXTURE, C: TENANT_C_FIXTURE } as const;

export function tenantForHost(host: string | null | undefined): TestTenant | undefined {
  if (!host) return undefined;
  const wanted = host.toLowerCase();
  return Object.values(TENANTS).find((tenant) => tenant.host === wanted);
}
