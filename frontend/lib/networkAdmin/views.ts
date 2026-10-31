import { badAnswer, bool, list, num, numOrNull, obj, oneOf, str, strOrNull, strings, type Obj } from '@/lib/operator/answers';

// What the network administrator's and the member's BFF routes make of the back end's answers
// (routes_network_admin.py, TEN-079, and the sharing read of TEN-081). Server-only. Each reader keeps the
// fields a screen shows and drops the rest: no tenant id, no account reference, nothing the back end adds
// later. A shape that is not the one expected is a fixed 502, never an empty list or a half page.

export const SCOPES = ['capacity', 'directory', 'criteria'] as const;
export type Scope = (typeof SCOPES)[number];
export const MEMBER_STATUSES = ['invited', 'active', 'left', 'removed'] as const;
export type MemberStatus = (typeof MEMBER_STATUSES)[number];
export const GRANT_STATUSES = ['proposed', 'grantor-approved', 'owner-approved', 'approved', 'declined', 'ended', 'lapsed', 'superseded'] as const;
export type GrantStatus = (typeof GRANT_STATUSES)[number];
export const LISTING_STATUSES = ['pending', 'admitted', 'declined', 'suspended', 'withdrawn'] as const;
export type ListingStatus = (typeof LISTING_STATUSES)[number];
export const LISTING_REASONS = ['outside-area', 'outside-pilot', 'duplicate-listing', 'data-quality', 'safety-concern', 'agreement-breach', 'other'] as const;
export type ListingReason = (typeof LISTING_REASONS)[number];
const END_REASONS = ['ended', 'lapsed', 'superseded'] as const;
const SOURCE_END_REASONS = ['left', 'grant-ended', 'replaced'] as const;

const TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
function time(value: unknown): string {
  const text = str(value, 40);
  if (!TIME.test(text)) throw badAnswer();
  return text;
}
function timeOrNull(value: unknown): string | null {
  return value === null || value === undefined ? null : time(value);
}

// ---------------------------------------------------------------- the networks

export type NetworkRow = {
  id: string;
  name: string;
  isOwner: boolean;
  membershipId: string;
  membershipStatus: 'invited' | 'active';
  agreementReference: string | null;
  agreementVersion: number | null;
  acceptedAgreementVersion: number | null;
  agreementBehind: boolean;
};

export function parseNetworks(value: unknown): NetworkRow[] {
  return list(obj(value).networks, 200).map((row) => {
    const r = obj(row);
    return {
      id: str(r.id, 31),
      name: str(r.name, 120),
      isOwner: bool(r.is_owner),
      membershipId: str(r.membership_id, 64),
      membershipStatus: oneOf(r.membership_status, ['invited', 'active'] as const),
      agreementReference: strOrNull(r.agreement_reference, 64),
      agreementVersion: numOrNull(r.agreement_version),
      acceptedAgreementVersion: numOrNull(r.accepted_agreement_version),
      agreementBehind: bool(r.agreement_behind),
    };
  });
}

// ---------------------------------------------------------------- the owner's views

export type MemberRow = {
  id: string;
  organisation: string;
  role: 'owner' | 'member';
  status: MemberStatus;
  invitedAt: string;
  joinedAt: string | null;
  leftAt: string | null;
  acceptedAgreementVersion: number | null;
  agreementBehind: boolean;
};

export function parseMembers(value: unknown): MemberRow[] {
  return list(obj(value).members, 2000).map((row) => {
    const r = obj(row);
    return {
      id: str(r.membership_id, 64),
      organisation: str(r.organisation_name, 120),
      role: oneOf(r.role, ['owner', 'member'] as const),
      status: oneOf(r.status, MEMBER_STATUSES),
      invitedAt: time(r.invited_at),
      joinedAt: timeOrNull(r.joined_at),
      leftAt: timeOrNull(r.left_at),
      acceptedAgreementVersion: numOrNull(r.accepted_agreement_version),
      agreementBehind: bool(r.agreement_behind),
    };
  });
}

export type KindState = { kind: Scope; status: 'active' | 'ended'; endedAt: string | null; endReason: (typeof SOURCE_END_REASONS)[number] | null };
export type HealthRow = { id: string; organisation: string; kinds: KindState[] };

function kindState(value: unknown, key: 'kind' | 'scope' = 'kind'): KindState {
  const k = obj(value);
  return {
    kind: oneOf(k[key], SCOPES),
    status: oneOf(k.status, ['active', 'ended'] as const),
    endedAt: timeOrNull(k.ended_at),
    endReason: k.end_reason === null || k.end_reason === undefined ? null : oneOf(k.end_reason, SOURCE_END_REASONS),
  };
}

export function parseProjection(value: unknown): HealthRow[] {
  return list(obj(value).members, 2000).map((row) => {
    const r = obj(row);
    return { id: str(r.membership_id, 64), organisation: str(r.organisation_name, 120), kinds: list(r.kinds, 10).map((k) => kindState(k, 'kind')) };
  });
}

export type GrantRow = {
  id: string;
  organisation: string;
  scope: Scope;
  status: GrantStatus;
  version: number;
  effectiveFrom: string;
  effectiveTo: string | null;
  agreementVersion: number;
  allowlistVersion: number;
  grantorApprovedAt: string | null;
  ownerApprovedAt: string | null;
  endedAt: string | null;
  endReason: (typeof END_REASONS)[number] | null;
  effective: boolean;
};

export function parseGrants(value: unknown): GrantRow[] {
  return list(obj(value).grants, 5000).map((row) => {
    const r: Obj = obj(row);
    return {
      id: str(r.id, 64),
      organisation: str(r.organisation_name, 120),
      scope: oneOf(r.scope, SCOPES),
      status: oneOf(r.status, GRANT_STATUSES),
      version: num(r.version),
      effectiveFrom: time(r.effective_from),
      effectiveTo: timeOrNull(r.effective_to),
      agreementVersion: num(r.agreement_version),
      allowlistVersion: num(r.allowlist_version),
      grantorApprovedAt: timeOrNull(r.grantor_approved_at),
      ownerApprovedAt: timeOrNull(r.owner_approved_at),
      endedAt: timeOrNull(r.ended_at),
      endReason: r.end_reason === null || r.end_reason === undefined ? null : oneOf(r.end_reason, END_REASONS),
      effective: bool(r.effective),
    };
  });
}

export type ListingRow = {
  id: string;
  organisation: string;
  serviceRef: string;
  status: ListingStatus;
  reason: ListingReason | null;
  requestedAt: string;
  decidedAt: string | null;
};

export function parseListings(value: unknown): ListingRow[] {
  return list(obj(value).listings, 5000).map((row) => {
    const r = obj(row);
    return {
      id: str(r.id, 64),
      organisation: str(r.organisation_name, 120),
      serviceRef: str(r.service_id, 64),
      status: oneOf(r.status, LISTING_STATUSES),
      reason: r.reason === null || r.reason === undefined ? null : oneOf(r.reason, LISTING_REASONS),
      requestedAt: time(r.requested_at),
      decidedAt: timeOrNull(r.decided_at),
    };
  });
}

// ---------------------------------------------------------------- the member's sharing

export type SharingNetwork = {
  id: string;
  name: string;
  membershipId: string;
  membershipStatus: MemberStatus;
  joinedAt: string | null;
  leftAt: string | null;
  agreementReference: string | null;
  agreementVersion: number | null;
  acceptedAgreementVersion: number | null;
  agreementBehind: boolean;
  shared: KindState[];
};

export type Allowlist = { version: number; scopes: Record<Scope, string[]> };
export type SharingRead = { allowlist: Allowlist; networks: SharingNetwork[] };

export function parseSharing(value: unknown): SharingRead {
  const body = obj(value);
  const allow = obj(body.allowlist);
  const scopes = obj(allow.scopes);
  return {
    allowlist: {
      version: num(allow.version),
      scopes: { capacity: strings(scopes.capacity, 80), directory: strings(scopes.directory, 80), criteria: strings(scopes.criteria, 80) },
    },
    networks: list(body.networks, 200).map((row) => {
      const r = obj(row);
      return {
        id: str(r.id, 31),
        name: str(r.name, 120),
        membershipId: str(r.membership_id, 64),
        membershipStatus: oneOf(r.membership_status, MEMBER_STATUSES),
        joinedAt: timeOrNull(r.joined_at),
        leftAt: timeOrNull(r.left_at),
        agreementReference: strOrNull(r.agreement_reference, 64),
        agreementVersion: numOrNull(r.agreement_version),
        acceptedAgreementVersion: numOrNull(r.accepted_agreement_version),
        agreementBehind: bool(r.agreement_behind),
        shared: list(r.shared, 10).map((k) => kindState(k, 'scope')),
      };
    }),
  };
}

/** The organisation's own grants in every network: each with the network it is in, to group them by. */
export type OwnGrant = GrantRow & { networkId: string };

export function parseOwnGrants(value: unknown): OwnGrant[] {
  const rows = list(obj(value).grants, 5000);
  const grants = parseGrants(value);
  return grants.map((grant, index) => ({ ...grant, networkId: str(obj(rows[index]).network_id, 31) }));
}
