import { GRANTS, LISTINGS, MEMBERS, OWNER_NETWORKS, PROJECTION, SHARING } from '@/test/fixtures/network-admin-shapes';
import { parseGrants, parseListings, parseMembers, parseNetworks, parseProjection, parseSharing } from '@/lib/networkAdmin/views';

// What the network administration and sharing BFF routes answer the browser (TEN-080, TEN-081): the back
// end's own shapes (network-admin-shapes.ts, written by the back end's converters) read through the same
// parsers the routes use, so a screen test never holds a shape the routes do not send.

const owned = parseNetworks(OWNER_NETWORKS)[0]!;
export const NETWORK = { id: owned.id, name: owned.name } as const;

export const VIEW_NETWORKS = { networks: [{ id: owned.id, name: owned.name }] };

export const VIEW_OVERVIEW = {
  network: {
    id: owned.id,
    name: owned.name,
    agreementReference: owned.agreementReference,
    agreementVersion: 2, // one ahead of the version the members accepted, so "behind" is something to say
    members: parseMembers(MEMBERS),
    health: parseProjection(PROJECTION),
  },
};

export const VIEW_GRANTS = { network: NETWORK, grants: parseGrants(GRANTS) };
export const VIEW_LISTINGS = { network: NETWORK, listings: parseListings(LISTINGS) };

export const VIEW_SHARING = (() => {
  const read = parseSharing(SHARING);
  return { allowlist: read.allowlist, networks: read.networks };
})();

// ---------------------------------------------------------------- the member's sharing page (TEN-081)

import type { GrantRow, GrantStatus, KindState, Scope } from '@/lib/networkAdmin/views';

export const ORGANISATION_CODE = 'sample-area-b';

/** One of the organisation's own grants, as the sharing route answers it. */
export function ownGrant(id: string, scope: Scope, status: GrantStatus, over: Partial<GrantRow> = {}): GrantRow {
  return {
    id,
    organisation: 'Sample Area B',
    scope,
    status,
    version: 1,
    effectiveFrom: '2026-10-04T09:00:00Z',
    effectiveTo: null,
    agreementVersion: 1,
    allowlistVersion: 1,
    grantorApprovedAt: null,
    ownerApprovedAt: null,
    endedAt: null,
    endReason: null,
    effective: false,
    ...over,
  };
}

export type SharingNetworkView = {
  id: string;
  name: string;
  isOwner: boolean;
  membershipStatus: 'invited' | 'active' | 'left' | 'removed';
  joinedAt: string | null;
  leftAt: string | null;
  agreementReference: string | null;
  agreementVersion: number | null;
  acceptedAgreementVersion: number | null;
  agreementBehind: boolean;
  shared: KindState[];
  grants: GrantRow[];
};

export function sharingNetwork(over: Partial<SharingNetworkView> = {}): SharingNetworkView {
  return {
    id: NETWORK.id,
    name: NETWORK.name,
    isOwner: false,
    membershipStatus: 'active',
    joinedAt: '2026-10-02T09:00:00Z',
    leftAt: null,
    agreementReference: 'DSA-2026-1',
    agreementVersion: 1,
    acceptedAgreementVersion: 1,
    agreementBehind: false,
    // Capacity waits for this organisation's approval; the directory is in force and arriving; criteria was never proposed.
    shared: [{ kind: 'directory', status: 'active', endedAt: null, endReason: null }],
    grants: [ownGrant('grant-cap', 'capacity', 'proposed'), ownGrant('grant-dir', 'directory', 'approved', { effective: true, grantorApprovedAt: '2026-10-04T09:00:00Z', ownerApprovedAt: '2026-10-04T10:00:00Z' })],
    ...over,
  };
}

export const VIEW_SHARING_PAGE = {
  organisationCode: ORGANISATION_CODE,
  allowlist: VIEW_SHARING.allowlist,
  networks: [sharingNetwork()],
};
