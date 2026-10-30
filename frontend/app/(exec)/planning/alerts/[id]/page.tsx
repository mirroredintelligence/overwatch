import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import { AlertDetail } from '@/components/exec/AlertDetail';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import { ALERT_ROLES, alertsByState } from '@/lib/exec/alertsServer';
import type { AlertItem } from '@/lib/exec/alerts';

export const metadata: Metadata = { title: 'Alert - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// An alert is read from the caller's own lists (open, then acknowledged, then closed): the back end has no
// single-alert read. The duty coordinator's number is the board's (DEC-777), or none.
export default async function ExecAlertPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  const { id } = await params;
  let alert: AlertItem | undefined;
  for (const state of ['open', 'acknowledged', 'closed'] as const) {
    alert = (await alertsByState(session, state)).find((item) => item.id === id);
    if (alert) break;
  }
  if (!alert) notFound();
  const phone = await readBoard(session).then((board) => board.coordinationPhone ?? null).catch(() => null);
  return (
    <main>
      <AlertDetail alert={alert} coordinationPhone={phone} />
    </main>
  );
}
