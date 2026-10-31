import { withBff } from '@/lib/bff/handler';
import { adminRead, NO_STORE } from '@/lib/networkAdmin/call';
import { listNetworks } from '@/lib/networkAdmin/network';
import { parseOwnGrants, parseSharing, type GrantRow, type OwnGrant } from '@/lib/networkAdmin/views';

// GET: what this organisation shares with each network it is in (TEN-081, design N2): the organisation's own
// code (the only identifier of itself it is given: the network owner needs it to invite it, and it is its own
// administrator who reads it), the allowlist (the exact fields that may leave a tenant, for each kind: the
// back end's own list), and for each network its membership (and whether the organisation owns it, which it
// cannot leave) and the agreement, what the network holds of the organisation now (states and dates, never a row) and the organisation's own grants there. The back end's
// answers are read field by field: no membership handle, no other organisation, nothing the back end adds.

/** A grant as the screen reads it: the network is the card it sits in, so it is not repeated on the grant. */
function withoutNetwork(grant: OwnGrant): GrantRow {
  const { networkId, ...rest } = grant;
  void networkId;
  return rest;
}

const get = withBff(
  async (_request, session) => {
    const sharing = parseSharing(await adminRead(session, '/network-admin/sharing'));
    const grants = parseOwnGrants(await adminRead(session, '/network-admin/grants'));
    const owned = new Set((await listNetworks(session)).filter((n) => n.isOwner).map((n) => n.id));
    return Response.json(
      {
        organisationCode: session.tenantId,
        allowlist: sharing.allowlist,
        networks: sharing.networks.map((network) => ({
          id: network.id,
          name: network.name,
          isOwner: owned.has(network.id),
          membershipStatus: network.membershipStatus,
          joinedAt: network.joinedAt,
          leftAt: network.leftAt,
          agreementReference: network.agreementReference,
          agreementVersion: network.agreementVersion,
          acceptedAgreementVersion: network.acceptedAgreementVersion,
          agreementBehind: network.agreementBehind,
          shared: network.shared,
          grants: grants.filter((g) => g.networkId === network.id).map((grant) => withoutNetwork(grant)),
        })),
      },
      { headers: NO_STORE },
    );
  },
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
