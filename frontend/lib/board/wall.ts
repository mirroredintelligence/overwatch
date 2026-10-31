import type { Session } from '@/lib/auth/session';
import { FhirError } from '@/lib/fhir/fhirError';
import { fhirFetch } from '@/lib/fhir/client';
import { badGateway, readBackendBody } from '@/lib/network/availability';
import { networkToWallBoard } from '@/lib/network/entries';
import { parseBoard } from '@/lib/network/parse';
import { readTenantProfile } from '@/lib/tenant/profile';
import { readBoard } from './read';
import { OWN_SCOPE, parseWallScope, WallScopeError, type WallScope } from './scope';
import type { Board } from './types';

// Server-only. What a wall screen shows (TEN-072): the back end says which board the screen shows
// (`GET /screens/me/board-scope`, W9B) and this reads that board, so the setting and the figures always
// come from one call and a screen never shows one scope's figures under another's header. The page and
// `GET /api/bff/wall/board` share it.
//
// The screen names nothing: its own record says which network (if any) it shows, and the answer holds the
// network's NAME only. A screen set to a network that is no longer open to it gets its own board with the
// `fallback` flag, and so does one whose network closes between the two reads (the 404 of the network
// board): it never shows a blank board, and never a network board it may no longer read. Any other failure
// of the network board stays a failure, so the screen shows its last known figures and says so.

export type WallBoard = { board: Board; scope: WallScope };

function unreadable(): FhirError {
  return badGateway();
}

async function readScope(session: Pick<Session, 'backendToken'>): Promise<WallScope> {
  const { data } = await fhirFetch<unknown>('/screens/me/board-scope', { token: session.backendToken, root: true, cache: 'no-store' });
  try {
    return parseWallScope(data);
  } catch (error) {
    if (error instanceof WallScopeError) throw unreadable();
    throw error;
  }
}

export async function readWallBoard(session: Pick<Session, 'backendToken' | 'role' | 'host'>): Promise<WallBoard> {
  // A person who reads the board (advisor, lead, exec) is not a screen: it has no setting, only its own board.
  if (session.role !== 'wall') return { board: await readBoard(session), scope: OWN_SCOPE };

  const scope = await readScope(session);
  if (scope.boardScope === 'network') {
    try {
      const { data } = await fhirFetch<unknown>('/screens/me/network-board', { token: session.backendToken, root: true, cache: 'no-store' });
      const network = readBackendBody(() => parseBoard(data, 'backend'));
      const profile = await readTenantProfile(session.host);
      return { board: networkToWallBoard(network, profile?.displayName ?? null), scope };
    } catch (error) {
      // The network closed to this screen between the two reads: its own board, with the flag.
      if (!(error instanceof FhirError && error.status === 404)) throw error;
      return { board: await readBoard(session), scope: { ...OWN_SCOPE, scopeVersion: scope.scopeVersion, fallback: true } };
    }
  }
  return { board: await readBoard(session), scope };
}
