import type { Session } from '@/lib/auth/session';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { readTenantProfile } from '@/lib/tenant/profile';
import { offeredNetworks, readBackendBody, requireOffered } from './availability';
import type { NetworkList } from './types';

// Server-only readers for the network routes (TEN-068). Every one asks the availability first, then
// reads the one network's route of the back end with the session's token, from the app root.

type Caller = Pick<Session, 'backendToken'>;

const NETWORK_ID = /^net-[a-z0-9][a-z0-9-]{1,26}$/;

function invalid(): FhirError {
  return new FhirError(400, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'The request was not valid.' }] });
}

/** The `networkId` of a request: one network id, or a 400. (The input guard has already checked the shape.) */
export function networkIdOf(request: Request): string {
  const value = new URL(request.url).searchParams.get('networkId');
  if (value === null || !NETWORK_ID.test(value)) throw invalid();
  return value;
}

/** `?history=true` for `history=true`, nothing for none or `false`, a 400 for anything else. */
export function historyQuery(request: Request): string {
  const value = new URL(request.url).searchParams.get('history');
  if (value === null || value === 'false') return '';
  if (value === 'true') return '?history=true';
  throw invalid();
}

/** One view of one network, after the availability check. `path` is the view; `query` starts with `?` or is empty. */
export async function readNetwork<T>(
  session: Caller,
  networkId: string,
  path: 'board' | 'directory' | 'criteria' | 'system-now' | 'phones' | 'week',
  parse: (body: unknown) => T,
  query = '',
): Promise<T> {
  await requireOffered(session, networkId);
  const { data } = await fhirFetch<unknown>(`/network/${networkId}/${path}${query}`, { token: session.backendToken, root: true });
  return readBackendBody(() => parse(data));
}

/** The networks the viewer may see, and the viewer's own organisation's name, to mark its rows. */
export async function readNetworkList(session: Pick<Session, 'backendToken' | 'host'>): Promise<NetworkList> {
  const networks = await offeredNetworks(session);
  const profile = await readTenantProfile(session.host);
  return { ownOrganisation: profile?.displayName ?? null, networks };
}
