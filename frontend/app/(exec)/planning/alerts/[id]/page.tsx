import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import { AlertDetail } from '@/components/exec/AlertDetail';
import { getSession } from '@/lib/auth/session';
import { ALERT_ROLES, openAlerts } from '@/lib/exec/alertsServer';

export const metadata: Metadata = { title: 'Alert - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// An alert is read from the caller's open alerts: the back end has no single-alert read. An alert that is
// no longer open is not found here.
export default async function ExecAlertPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  const { id } = await params;
  const alert = (await openAlerts(session)).find((item) => item.id === id);
  if (!alert) notFound();
  return (
    <main>
      <AlertDetail alert={alert} />
    </main>
  );
}
