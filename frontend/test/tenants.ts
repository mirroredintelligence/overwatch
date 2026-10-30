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

// ---------------------------------------------------------------------------------------------
// The network, the grants and the records (TEN-047, audit D 7.2).
//
// Tenants A and B are members of one network; C is not. A and B hold records with the SAME
// identifiers (a service `s1`, a case reference `4821`, a phone ending, a registration id) and
// DIFFERENT content, so a handler that forgets the tenant returns the wrong record instead of a 404
// and the wrong record cannot be mistaken for the right one. One id exists only in A. Names are
// fictional and distinct; there is no person, phone number, postcode or NHS number.

export const NETWORK = {
  id: 'net-sample',
  displayName: 'Sample Network',
  memberIds: [TENANT_A_FIXTURE.id, TENANT_B_FIXTURE.id] as readonly string[],
} as const;

export type GrantState = 'active' | 'ended' | 'pending';
export type TestGrant = { readonly id: string; readonly grantorId: string; readonly networkId: string; readonly state: GrantState };

export const GRANTS: readonly TestGrant[] = [
  { id: 'grant-a', grantorId: TENANT_A_FIXTURE.id, networkId: NETWORK.id, state: 'active' },
  { id: 'grant-b', grantorId: TENANT_B_FIXTURE.id, networkId: NETWORK.id, state: 'ended' },
  { id: 'grant-c', grantorId: TENANT_C_FIXTURE.id, networkId: NETWORK.id, state: 'pending' },
];

/** The identifiers that two tenants hold at once. */
export const SHARED_IDS = {
  serviceId: 's1',
  caseReference: '4821',
  phoneEnding: '0123',
  registrationId: 'reg-1',
} as const;

/** The identifiers that exist in tenant A only. */
export const ONLY_IN_A = { serviceId: 'a-only-1', caseReference: '4822' } as const;

export type TenantRecords = {
  readonly services: readonly { id: string; name: string }[];
  readonly cases: readonly { reference: string; note: string }[];
  readonly phoneEnding: string;
  readonly registrationId: string;
};

const RECORDS: Readonly<Record<string, TenantRecords>> = {
  [TENANT_A_FIXTURE.id]: {
    services: [
      { id: SHARED_IDS.serviceId, name: 'Alder Community Beds' },
      { id: ONLY_IN_A.serviceId, name: 'Alder Reablement Team' },
    ],
    cases: [
      { reference: SHARED_IDS.caseReference, note: 'Sample case recorded in tenant A' },
      { reference: ONLY_IN_A.caseReference, note: 'Second sample case in tenant A' },
    ],
    phoneEnding: SHARED_IDS.phoneEnding,
    registrationId: SHARED_IDS.registrationId,
  },
  [TENANT_B_FIXTURE.id]: {
    services: [{ id: SHARED_IDS.serviceId, name: 'Birch Community Beds' }],
    cases: [{ reference: SHARED_IDS.caseReference, note: 'Sample case recorded in tenant B' }],
    phoneEnding: SHARED_IDS.phoneEnding,
    registrationId: SHARED_IDS.registrationId,
  },
  [TENANT_C_FIXTURE.id]: {
    services: [{ id: 'c-only-1', name: 'Cedar Virtual Ward' }],
    cases: [{ reference: '4999', note: 'Sample case recorded in tenant C' }],
    phoneEnding: '0456',
    registrationId: 'reg-9',
  },
};

/** The records a tenant holds, or undefined for a tenant the fixture does not know. */
export function recordsFor(tenantId: string): TenantRecords | undefined {
  return RECORDS[tenantId];
}
