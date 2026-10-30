import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { AlertList } from '@/components/exec/AlertList';
import { Banner } from '@/components/ui/Banner';
import { getSession } from '@/lib/auth/session';
import { ALERT_ROLES, openAlerts } from '@/lib/exec/alertsServer';
import type { AlertItem } from '@/lib/exec/alerts';

export const metadata: Metadata = { title: 'Alerts - DIUCS capacity' };
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
  return (
    <main>
      <AlertList open={open} />
    </main>
  );
}
