'use client';

import { useRouter } from 'next/navigation';
import type { FetchedBoard } from '@/lib/board/client';
import type { Board as BoardData } from '@/lib/board/types';
import type { WallScope } from '@/lib/board/scope';
import { useBoardFeed, type StreamSource } from '@/lib/board/useBoardFeed';
import { Board } from './Board';
import styles from './LiveBoard.module.css';
import { StatusAnnouncer } from './StatusAnnouncer';

// The wall board, kept current. The page reads the first board on the server; this
// listens to the live stream (through the BFF, as the paired screen's session) and
// refetches, and shows Last known when the board cannot be refreshed or is too
// old. It never sends, chooses or reads a tenant: the session says whose board it
// is (DEC-130, DEC-132).

export type LiveBoardProps = {
  initialBoard: BoardData;
  /** The tenant's own line under the heading, read by the page from the profile (TEN-049). */
  subtitle?: string | null;
  /** The tenant's own heading, built by the page from the profile (TEN-069), or none. */
  heading?: string | null;
  /** The web server's clock (epoch ms) when it read `initialBoard`. */
  serverTime: number;
  /** Which board the page read `initialBoard` under (TEN-072). Absent: the screen's own organisation's. */
  initialScope?: WallScope;
  // Seams for tests. Production uses the defaults.
  fetchBoard?: (signal: AbortSignal) => Promise<FetchedBoard>;
  createEventSource?: (scope: WallScope) => StreamSource | null;
  now?: () => number;
  onUnpaired?: () => void;
};

const STREAM_URL = '/api/bff/events';
// A screen that shows a network listens to the network's own channel; it names no network (its record does).
const NETWORK_STREAM_URL = '/api/bff/wall/network-events';
const PAIR = '/screen/pair';

function openStream(scope: WallScope): StreamSource | null {
  if (typeof EventSource === 'undefined') return null;
  return new EventSource(scope.boardScope === 'network' ? NETWORK_STREAM_URL : STREAM_URL);
}

export function LiveBoard({
  initialBoard,
  subtitle = null,
  heading = null,
  serverTime,
  initialScope,
  fetchBoard,
  createEventSource = openStream,
  now,
  onUnpaired,
}: LiveBoardProps) {
  const router = useRouter();
  const { board, assessment, scope, lastNetworkName } = useBoardFeed({
    initialBoard,
    serverTime,
    initialScope,
    fetchBoard,
    createEventSource,
    now,
    // A refused screen is not paired (or no longer): the pairing page, as on first load (DEC-151 item 4).
    onUnpaired: onUnpaired ?? (() => router.replace(PAIR)),
  });
  return (
    // The wall's dark ground (artboard WallBoard), in every state: current, stream paused and last known.
    <div className={styles.wall} data-el="WALL-GROUND" data-surface="wall">
      {/* Status changes, said politely once (KI-56). */}
      <StatusAnnouncer board={board} lastKnown={assessment.mode === 'last-known'} />
      {assessment.mode === 'last-known' ? (
        <Board board={board} lastKnown={assessment} subtitle={subtitle} heading={heading} scope={scope} fellBackFrom={lastNetworkName} />
      ) : (
        <Board board={board} streamPaused={assessment.streamPaused} subtitle={subtitle} heading={heading} scope={scope} fellBackFrom={lastNetworkName} />
      )}
    </div>
  );
}
