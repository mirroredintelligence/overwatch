import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { SettingsForm } from '@/components/exec/SettingsForm';
import { Banner } from '@/components/ui/Banner';
import { getSession } from '@/lib/auth/session';
import { readLeaders } from '@/lib/exec/leaders';
import { readAlertPreferences } from '@/lib/exec/subscriptions';

export const metadata: Metadata = { title: 'Alert settings - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// Alerts and escalation, reachable after set-up (W39).
export default async function ExecSettingsPage() {
  const session = await getSession();
  if (!session || (session.role !== 'exec' && session.role !== 'lead')) redirect('/sign-in');
  let stored;
  try {
    stored = await readAlertPreferences(session);
  } catch {
    return (
      <main>
        <Banner tone="offline" title="Your alert settings could not be loaded. Try again shortly." />
      </main>
    );
  }
  return (
    <main>
      <h1>Alert settings</h1>
      <SettingsForm initial={stored.preferences} leaders={await readLeaders(session)} />
    </main>
  );
}
