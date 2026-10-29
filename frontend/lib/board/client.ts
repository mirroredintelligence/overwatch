import { withTraceparent } from '@/lib/telemetry/trace';
import { parseBoardJson } from './boardJson';
import type { Board } from './types';

// The browser's read of GET /api/bff/board: same origin, the session cookie, no
// query string and no header of its own. Whose board it is comes from the
// session's back-end token alone (DEC-130, DEC-132). Every way it can go wrong is
// a BoardFetchError with a fixed message, so nothing from an answer is kept.

export type FetchedBoard = {
  board: Board;
  /** The back end's clock (epoch ms) from the Date header of the answer, or null when it had none. */
  serverTime: number | null;
};

export type BoardFetchKind = 'unreachable' | 'refused' | 'unreadable';

export class BoardFetchError extends Error {
  readonly kind: BoardFetchKind;
  readonly status: number | null;

  constructor(kind: BoardFetchKind, status: number | null = null) {
    super('The board could not be refreshed.');
    this.name = 'BoardFetchError';
    this.kind = kind;
    this.status = status;
  }
}

export const BOARD_URL = '/api/bff/board';

/** The statuses that mean this screen is not (or no longer) paired. */
export const REFUSED_STATUSES: readonly number[] = [401, 403, 404];

function kindFor(status: number): BoardFetchKind {
  if (REFUSED_STATUSES.includes(status)) return 'refused';
  // The BFF answers 502 when the back end sent a board it could not read.
  if (status === 502) return 'unreadable';
  return 'unreachable';
}

function serverTimeOf(response: Response): number | null {
  const time = Date.parse(response.headers.get('Date') ?? '');
  return Number.isNaN(time) ? null : time;
}

export async function fetchBoardFromBff(signal?: AbortSignal): Promise<FetchedBoard> {
  let response: Response;
  try {
    response = await fetch(
      BOARD_URL,
      withTraceparent({ method: 'GET', cache: 'no-store', credentials: 'same-origin', signal }),
    );
  } catch {
    throw new BoardFetchError('unreachable');
  }
  if (!response.ok) throw new BoardFetchError(kindFor(response.status), response.status);

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    // A body that is not JSON, or one that was cut off by an abort.
    throw new BoardFetchError(signal?.aborted ? 'unreachable' : 'unreadable', response.status);
  }
  try {
    return { board: parseBoardJson(body), serverTime: serverTimeOf(response) };
  } catch {
    throw new BoardFetchError('unreadable', response.status);
  }
}
