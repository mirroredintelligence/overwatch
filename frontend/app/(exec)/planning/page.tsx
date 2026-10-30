import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { ExecHome } from '@/components/exec/ExecHome';
import { Banner } from '@/components/ui/Banner';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import type { Board } from '@/lib/board/types';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';

export const metadata: Metadata = { title: 'Home - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// The executive's home (W40). The board is read through the back end with the caller's token; the name
// is the organisation's, from the board (DEC-151), and no constant names it.
export default async function ExecHomePage() {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  let board: Board | null = null;
  try {
    board = await readBoard(session);
  } catch {
    board = null;
  }
  if (board === null) {
    return (
      <main>
        <Banner tone="offline" title="The board could not be read. Try again shortly." />
      </main>
    );
  }
  return (
    <main>
      <ExecHome board={board} name={board.organisation ?? 'Your system'} phoneAlerts={session.role === 'exec'} />
    </main>
  );
}
