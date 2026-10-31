import type { Role, Session } from '@/lib/auth/session';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { NetworkParseError, parseNetworks } from './parse';
import type { NetworkSummary } from './types';

// The availability check of the network routes (TEN-068), made on EVERY call and never kept. A page
// names a network by the id the server offered; this asks the back end which networks THIS session's
// tenant may see now (the registry, through `GET /networks`; the token's claim only routes) and lets a
// call through only for one of them. A tenant that is not a member, a member that left, an unknown
// network and an id that was never offered are one 404 (DEC-134, audit D risk 6), and for each the
// network's own routes are not called at all, so no call carries a token to a network it cannot read.
//
// Server-only. No tenant, scope or network is sent to the back end except as the id in the path of the
// call that follows, after this check.

/** The roles that see a network: the back end's `NETWORK_VIEW_ROLES`. A wall is not one. */
export const NETWORK_VIEW_ROLES: Role[] = ['advisor', 'clinical', 'lead', 'owner', 'exec'];
/** The roles that read the week: the executive and the shift lead. */
export const NETWORK_WEEK_ROLES: Role[] = ['exec', 'lead'];

type Caller = Pick<Session, 'backendToken'>;

function notFound(): FhirError {
  return new FhirError(404, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }],
  });
}

/** A body the back end sent that this front end cannot read: a bad gateway, nothing of the body kept. */
export function badGateway(): FhirError {
  return new FhirError(502, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned a network answer that could not be read.' }],
  });
}

/** Runs a parser over the back end's body; a body it refuses is a 502, never an error with the body in it. */
export function readBackendBody<T>(parse: () => T): T {
  try {
    return parse();
  } catch (error) {
    if (error instanceof NetworkParseError) throw badGateway();
    throw error;
  }
}

/** The networks the session's tenant may see now, from the registry. */
export async function offeredNetworks(session: Caller): Promise<NetworkSummary[]> {
  const { data } = await fhirFetch<unknown>('/networks', { token: session.backendToken, root: true });
  return readBackendBody(() => parseNetworks(data, 'backend'));
}

/** The offered network with this id, or the one 404. */
export async function requireOffered(session: Caller, networkId: string): Promise<NetworkSummary> {
  const found = (await offeredNetworks(session)).find((network) => network.id === networkId);
  if (found === undefined) throw notFound();
  return found;
}
