import type { Board } from './types';

// The browser's read of GET /api/bff/board.
export type FetchedBoard = { board: Board; serverTime: number | null };

export type BoardFetchKind = 'unreachable' | 'refused' | 'unreadable';

export class BoardFetchError extends Error {
  readonly kind: BoardFetchKind;
  readonly status: number | null;

  constructor(kind: BoardFetchKind, status: number | null = null) {
    super('The board could not be refreshed.');
    this.name = 'BoardFetchError';
    this.kind = 'unreachable';
    this.status = null;
    void kind;
    void status;
  }
}

export async function fetchBoardFromBff(signal?: AbortSignal): Promise<FetchedBoard> {
  void signal;
  return { board: null as unknown as Board, serverTime: null };
}
