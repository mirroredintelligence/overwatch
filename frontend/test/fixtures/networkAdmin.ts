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
