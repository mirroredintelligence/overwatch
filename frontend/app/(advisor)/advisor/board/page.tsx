import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { Board } from '@/components/board/Board';
import { BoardUnavailable } from '@/components/board/BoardUnavailable';
import { getSession } from '@/lib/auth/session';
import { canReadBoard, readBoard } from '@/lib/board/read';
import { FhirError } from '@/lib/fhir/client';

export const metadata: Metadata = {
  title: 'Wall board view · DIUCS capacity',
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
  return (
    <>
      <p>
        <a href="/advisor">Back to advisor home</a>
      </p>
      <Board board={board} />
    </>
  );
}
