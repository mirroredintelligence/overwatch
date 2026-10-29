'use client';

import { useRouter } from 'next/navigation';
import type { FetchedBoard } from '@/lib/board/client';
import type { Board as BoardData } from '@/lib/board/types';
import { useBoardFeed, type StreamSource } from '@/lib/board/useBoardFeed';
import { Board } from './Board';

// The wall board, kept current. The page reads the first board on the server; this
// listens to the live stream (through the BFF, as the paired screen's session) and
// refetches, and shows Last known when the board cannot be refreshed or is too
// old. It never sends, chooses or reads a tenant: the session says whose board it
// is (DEC-130, DEC-132).

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

const STREAM_URL = '/api/bff/events';
const PAIR = '/screen/pair';

function openStream(): StreamSource | null {
  return typeof EventSource === 'undefined' ? null : new EventSource(STREAM_URL);
}

export function LiveBoard({
  initialBoard,
  serverTime,
  fetchBoard,
  createEventSource = openStream,
  now,
  onUnpaired,
}: LiveBoardProps) {
  const router = useRouter();
  const { board, assessment } = useBoardFeed({
    initialBoard,
    serverTime,
    fetchBoard,
    createEventSource,
    now,
    // A refused screen is not paired (or no longer): the pairing page, as on first load (DEC-151 item 4).
    onUnpaired: onUnpaired ?? (() => router.replace(PAIR)),
  });
  return assessment.mode === 'last-known' ? (
    <Board board={board} lastKnown={assessment} />
  ) : (
    <Board board={board} streamPaused={assessment.streamPaused} />
  );
}
