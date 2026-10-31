import type { Session } from '@/lib/auth/session';
import { invalidRequest } from '@/lib/lead/bffInput';
import { adminRead } from './call';
import { NETWORK_ID, notFound } from './ids';
import { parseNetworks, type NetworkRow } from './views';

// Which network a call is about (TEN-080, TEN-081). The registry decides, never the browser: every call
// first asks the back end which networks THIS session's organisation belongs to (the registry, through
// `GET /network-admin/networks`; the token's own claim is not used) and goes on only for one of them. The
// browser may name one of the networks the server offered, as the query key `networkId` that the input
// guard lets through on the routes that say so; it is a choice among offered networks and never an
// authority, and an id that was not offered is the same 404 as a network that is not the caller's. With
// none named and exactly one that fits, that one; with several, a 400 (the overview offers the list).
//
// Server-only. The network id reaches the back end only in the path of the call that follows.

type Caller = Pick<Session, 'backendToken'>;

/** The networks this organisation belongs to or is invited to, from the registry. */
export async function listNetworks(session: Caller): Promise<NetworkRow[]> {
  return parseNetworks(await adminRead(session, '/network-admin/networks'));
}

/** The networks the organisation owns and is active in: the ones its network administrator runs. */
export const ownedNetworks = (networks: NetworkRow[]): NetworkRow[] => networks.filter((n) => n.isOwner && n.membershipStatus === 'active');

/** The `networkId` the browser named, or null. (The input guard has already checked its shape.) */
export function namedNetwork(request: Request): string | null {
  const value = new URL(request.url).searchParams.get('networkId');
  if (value === null) return null;
  if (!NETWORK_ID.test(value)) throw invalidRequest();
  return value;
}

/**
 * The one network of those that fit. Named: it must be among them, or the one 404 (the same as for a
 * network that is not the caller's, and no network route is called). Not named: the only one, a 404 for
 * none, a 400 for several.
 */
export function chooseNetwork(fitting: NetworkRow[], named: string | null): NetworkRow {
  if (named !== null) {
    const found = fitting.find((network) => network.id === named);
    if (found === undefined) throw notFound();
    return found;
  }
  const [only, ...more] = fitting;
  if (only === undefined) throw notFound();
  if (more.length > 0) throw invalidRequest();
  return only;
}

/** The owner's network for this request, after asking the registry. */
export async function ownerNetwork(session: Caller, request: Request): Promise<NetworkRow> {
  return chooseNetwork(ownedNetworks(await listNetworks(session)), namedNetwork(request));
}
