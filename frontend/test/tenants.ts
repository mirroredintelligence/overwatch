import { DIRECTORY_A, DIRECTORY_B } from '@/test/oidc/constants';

// The tenants the front-end tests sign in as. Sample values only: nothing here is a real
// organisation, host or directory. A third tenant has no directory bound, so a test can show that a
// person of tenant A or B gets nothing there. Hosts are one sub-domain per tenant (DEC-134 item 3).

/** The public profile of a tenant as the back end answers it (`GET /public/tenant-profile`). */
export type TestProfile = {
  displayName: string;
  timeZone: string;
  locale: string;
  wording: { systemName: string; referralSystemName: string; coordinationTeamName: string } | null;
  coordinationPhone: string | null;
};

export type TestTenant = {
  readonly id: string;
  readonly host: string;
  readonly displayName: string;
  /** The Entra directory the tenant has bound, or null when it has none. */
  readonly directoryId: string | null;
  /** What the public profile answers for the tenant's host; null when it answers as a host nobody owns. */
  readonly profile: TestProfile | null;
};

export const TENANT_A_FIXTURE: TestTenant = {
  id: 'trust-a',
  host: 'tenant-a.example.test',
  displayName: 'Sample Area A',
  directoryId: DIRECTORY_A,
  // Sample words and a number from the Ofcom drama range: nothing here is a real organisation.
  profile: {
    displayName: 'Sample Area A',
    timeZone: 'Europe/London',
    locale: 'en-GB',
    wording: { systemName: 'Capacity A', referralSystemName: 'Referral system A', coordinationTeamName: 'Access team A' },
    coordinationPhone: '01632 960001',
  },
};

export const TENANT_B_FIXTURE: TestTenant = {
  id: 'trust-b',
  host: 'tenant-b.example.test',
  displayName: 'Sample Area B',
  directoryId: DIRECTORY_B,
  profile: {
    displayName: 'Sample Area B',
    timeZone: 'Europe/London',
    locale: 'en-GB',
    wording: { systemName: 'Capacity B', referralSystemName: 'Referral system B', coordinationTeamName: 'Access team B' },
    coordinationPhone: '01632 960002',
  },
};

export const TENANT_C_FIXTURE: TestTenant = {
  id: 'trust-c',
  host: 'tenant-c.example.test',
  displayName: 'Sample Area C',
  directoryId: null,
  // A tenant with no configuration in force: a profile with no wording and no phone.
  profile: {
    displayName: 'Sample Area C',
    timeZone: 'Europe/London',
    locale: 'en-GB',
    wording: null,
    coordinationPhone: null,
  },
};

export const TENANTS = { A: TENANT_A_FIXTURE, B: TENANT_B_FIXTURE, C: TENANT_C_FIXTURE } as const;

export function tenantForHost(host: string | null | undefined): TestTenant | undefined {
  if (!host) return undefined;
  const wanted = host.toLowerCase();
  return Object.values(TENANTS).find((tenant) => tenant.host === wanted);
}
