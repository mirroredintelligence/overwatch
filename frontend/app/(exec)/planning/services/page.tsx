import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { ServiceList } from '@/components/exec/ServiceList';
import { Banner } from '@/components/ui/Banner';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import type { Board } from '@/lib/board/types';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';

export const metadata: Metadata = { title: 'All services - DIUCS capacity' };
export const dynamic = 'force-dynamic';

export default async function ExecServicesPage() {
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
        <Banner tone="offline" title="The services could not be read. Try again shortly." />
      </main>
    );
  }
  return (
    <main>
      <h1>All services</h1>
      <ServiceList entries={board.entries} />
    </main>
  );
}
