import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { StartCallButton } from '@/components/advisor/StartCallButton';
import { Board } from '@/components/board/Board';
import { BoardUnavailable } from '@/components/board/BoardUnavailable';
import { getSession } from '@/lib/auth/session';
import { canReadBoard, readBoard } from '@/lib/board/read';
import { FhirError } from '@/lib/fhir/fhirError';

export const metadata: Metadata = {
  title: 'Live board · Overwatch',
};

// Read at every request: a board is never cached. The advisor sees the same board as the wall,
// for the advisor's own session. It takes no input (no tenant, no organisation, no scope).
export const dynamic = 'force-dynamic';

export default async function AdvisorBoardPage() {
  const session = await getSession();
  if (!session || !canReadBoard(session.role)) redirect('/sign-in');

  let board: Awaited<ReturnType<typeof readBoard>>;
  try {
    board = await readBoard(session);
  } catch (error) {
    if (error instanceof FhirError && [401, 403, 404].includes(error.status)) redirect('/sign-in');
    return <BoardUnavailable />;
  }
  // The staff frame's rail is the way home, so the page draws no "back" link; Start a new call is its one
  // primary action (BoardNormal).
  return (
    <Board
      board={board}
      view="advisor"
      action={<StartCallButton />}
      ownSwitch={{ ownHref: '/advisor/board', networkHref: '/network/board' }}
    />
  );
}
