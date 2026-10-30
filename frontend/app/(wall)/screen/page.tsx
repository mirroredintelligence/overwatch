import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { LiveBoard } from '@/components/board/LiveBoard';
import { BoardUnavailable } from '@/components/board/BoardUnavailable';
import { getSession } from '@/lib/auth/session';
import { serverNow } from '@/lib/board/clock';
import { canReadBoard, readBoard } from '@/lib/board/read';
import type { Board as BoardData } from '@/lib/board/types';
import { copy } from '@/lib/copy';
import { FhirError } from '@/lib/fhir/client';
import { readTenantProfile } from '@/lib/tenant/profile';

// The layout's template adds the product name; no organisation is named here.
export const metadata: Metadata = {
  title: 'Wall screen',
};

// Read at every request: a wall board is never cached.
export const dynamic = 'force-dynamic';

const PAIR = '/screen/pair';
// Where a screen the back end no longer lets read goes. Not PAIR: the pairing page sends a display that
// still holds a wall session back here, so the two would loop (W9I).
const RECONNECT = '/screen/reconnect';

// The page takes no input. Which organisation's board this is comes from the
// paired screen's own session and its back-end token, never from the address,
// a query string or anything else the browser sends (DEC-130, DEC-132).
export default async function WallScreenPage() {
  const session = await getSession();
  if (!session || !canReadBoard(session.role)) redirect(PAIR);

  let board: BoardData;
  let serverTime: number;
  try {
    board = await readBoard(session);
    // The web server's clock when the board was read: the browser measures the
    // board's age against it, not against its own clock (DEC-152).
    serverTime = serverNow();
  } catch (error) {
    // The back end does not know this screen (or no longer lets it read the board, as when a lead has
    // disconnected it): ask for a new session, or pair again.
    if (error instanceof FhirError && [401, 403, 404].includes(error.status)) redirect(RECONNECT);
    // Anything else: show no figure at all, and say what to do.
    return <BoardUnavailable />;
  }
  // The line under the heading is the tenant's own, from the profile of the host the session was made
  // on; none when the tenant has not set one or the profile cannot be read.
  const subtitle = copy.wallSubtitle(await readTenantProfile(session.host));
  return <LiveBoard initialBoard={board} serverTime={serverTime} subtitle={subtitle} />;
}
