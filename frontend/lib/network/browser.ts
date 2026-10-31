import { bffGet, type BffResult } from '@/lib/bff/client';
import { withTraceparent } from '@/lib/telemetry/trace';
import { parseBoard, parseNetworkList } from './parse';
import type { NetworkBoard, NetworkList } from './types';

// The browser's reads of its own BFF's network routes (TEN-068, TEN-070). The one place a network id is
// put on a request is the `networkId` query key of these routes: the id the server offered in the list,
// never a header, never a body, never storage and never the address of a page. Every way a read can go
// wrong is a fixed answer, so nothing from an answer is kept in an error.

const BASE = '/api/bff/network';

export type NetworkView = 'board' | 'directory' | 'criteria' | 'system-now' | 'phones' | 'week';

function viewUrl(view: string, networkId: string, extra = ''): string {
  return `${BASE}/${view}?networkId=${encodeURIComponent(networkId)}${extra === '' ? '' : `&${extra}`}`;
}

/** The stream of a network's board: the BFF's relay, the network named by the one key. */
export function networkEventsUrl(networkId: string): string {
  return viewUrl('events', networkId);
}

/** The networks the viewer may see, and the viewer's own organisation's name. */
export function readNetworkList(): Promise<BffResult<NetworkList>> {
  return bffGet(BASE, parseNetworkList);
}

/** One view of a network. `extra` is one more query pair the view takes (`history=true`, `weekStart=...`). */
export function readNetworkView<T>(view: NetworkView, networkId: string, parse: (body: unknown) => T, extra = ''): Promise<BffResult<T>> {
  return bffGet(viewUrl(view, networkId, extra), parse);
}

export type NetworkFetchKind = 'unreachable' | 'refused' | 'unreadable';

export class NetworkFetchError extends Error {
  readonly kind: NetworkFetchKind;
  readonly status: number | null;

  constructor(kind: NetworkFetchKind, status: number | null = null) {
    super('The network board could not be refreshed.');
    this.name = 'NetworkFetchError';
    this.kind = kind;
    this.status = status;
  }
}

export type FetchedNetworkBoard = {
  board: NetworkBoard;
  /** The back end's clock (epoch ms) from the Date header of the answer, or null when it had none. */
  serverTime: number | null;
};

/** The statuses that mean the viewer may not read this network (now). */
export const NETWORK_REFUSED_STATUSES: readonly number[] = [401, 403, 404];

function kindFor(status: number): NetworkFetchKind {
  if (NETWORK_REFUSED_STATUSES.includes(status)) return 'refused';
  // The BFF answers 502 when the back end sent a board it could not read.
  if (status === 502) return 'unreadable';
  return 'unreachable';
}

export async function fetchNetworkBoard(networkId: string, signal?: AbortSignal): Promise<FetchedNetworkBoard> {
  let response: Response;
  try {
    response = await fetch(
      `/api/bff/network/board?networkId=${encodeURIComponent(networkId)}`,
      withTraceparent({ method: 'GET', cache: 'no-store', credentials: 'same-origin', signal }),
    );
  } catch {
    throw new NetworkFetchError('unreachable');
  }
  if (!response.ok) throw new NetworkFetchError(kindFor(response.status), response.status);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new NetworkFetchError(signal?.aborted ? 'unreachable' : 'unreadable', response.status);
  }
  const date = Date.parse(response.headers.get('Date') ?? '');
  try {
    return { board: parseBoard(body, 'bff'), serverTime: Number.isNaN(date) ? null : date };
  } catch {
    throw new NetworkFetchError('unreadable', response.status);
  }
}
