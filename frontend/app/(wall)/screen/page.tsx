import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { Board } from '@/components/board/Board';
import { BoardUnavailable } from '@/components/board/BoardUnavailable';
import { getSession } from '@/lib/auth/session';
import { canReadBoard, readBoard } from '@/lib/board/read';
import type { Board as BoardData } from '@/lib/board/types';
import { FhirError } from '@/lib/fhir/client';

export const metadata: Metadata = {
  title: 'DIUCS capacity wall screen',
};

// Read at every request: a wall board is never cached.
export const dynamic = 'force-dynamic';

const PAIR = '/screen/pair';

// The page takes no input. Which organisation's board this is comes from the
// paired screen's own session and its back-end token, never from the address,
// a query string or anything else the browser sends (DEC-130, DEC-132).
export default async function WallScreenPage() {
  const session = await getSession();
  if (!session || !canReadBoard(session.role)) redirect(PAIR);

  let board: BoardData;
  try {
    board = await readBoard(session);
  } catch (error) {
    // The back end does not know this screen (or no longer lets it read the board): pair again.
    if (error instanceof FhirError && [401, 403, 404].includes(error.status)) redirect(PAIR);
    // Anything else: show no figure at all, and say what to do.
    return <BoardUnavailable />;
  }
  return <Board board={board} />;
}
