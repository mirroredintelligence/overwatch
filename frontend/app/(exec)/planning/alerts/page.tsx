import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { AlertList } from '@/components/exec/AlertList';
import { Banner } from '@/components/ui/Banner';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import { ALERT_ROLES, openAlerts } from '@/lib/exec/alertsServer';
import type { AlertItem } from '@/lib/exec/alerts';

export const metadata: Metadata = { title: 'Alerts - Overwatch' };
export const dynamic = 'force-dynamic';

export default async function ExecAlertsPage() {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  let open: AlertItem[] | null = null;
  try {
    open = await openAlerts(session);
  } catch {
    open = null;
  }
  if (open === null) {
    return (
      <main>
        <Banner tone="offline" title="Your alerts could not be read. Try again shortly." />
      </main>
    );
  }
  // The duty coordinator's number is the board's (DEC-777), or none: the call is left out when it cannot be read.
  const phone = await readBoard(session).then((board) => board.coordinationPhone ?? null).catch(() => null);
  return (
    <main>
      <AlertList open={open} coordinationPhone={phone} />
    </main>
  );
}
