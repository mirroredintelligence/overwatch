import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { PhoneAlerts } from '@/components/exec/PhoneAlerts';
import { getSession } from '@/lib/auth/session';

export const metadata: Metadata = { title: 'Alerts on this phone - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// Alerts on the executive's phone (W9H, DEC-1040). An executive holds no post, so this is the one part of
// the installed app they use. The notification routes admit an executive and a reporter, so a lead, who
// shares /planning, goes to the home screen rather than to a button that would be refused.
export default async function PhoneAlertsPage() {
  const session = await getSession();
  if (session?.role === 'lead') redirect('/planning');
  if (!session || session.role !== 'exec') redirect('/sign-in');
  return (
    <main>
      <PhoneAlerts />
    </main>
  );
}
