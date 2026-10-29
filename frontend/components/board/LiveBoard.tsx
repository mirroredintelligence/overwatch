'use client';

import type { FetchedBoard } from '@/lib/board/client';
import type { StreamSource } from '@/lib/board/useBoardFeed';
import type { Board as BoardData } from '@/lib/board/types';
import { Board } from './Board';

export type LiveBoardProps = {
  initialBoard: BoardData;
  /** The web server's clock (epoch ms) when it read `initialBoard`. */
  serverTime: number;
  // Seams for tests. Production uses the defaults.
  fetchBoard?: (signal: AbortSignal) => Promise<FetchedBoard>;
  createEventSource?: () => StreamSource | null;
  now?: () => number;
  onUnpaired?: () => void;
};

export function LiveBoard({ initialBoard }: LiveBoardProps) {
  return <Board board={initialBoard} />;
}
