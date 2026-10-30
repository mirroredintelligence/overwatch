import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { SetupFlow } from '@/components/exec/SetupFlow';
import { getSession } from '@/lib/auth/session';
import { DEFAULT_ALERT_PREFERENCES } from '@/lib/exec/alertPrefs';
import { readLeaders } from '@/lib/exec/leaders';
import { readAlertPreferences } from '@/lib/exec/subscriptions';

export const metadata: Metadata = { title: 'Set up alerts - DIUCS capacity' };
// Read at every request: the saved choices are the person's own and never cached.
export const dynamic = 'force-dynamic';

// The executive's set-up (W39). The route is /planning: the guard and the sign-in home already name it
// (DEC-210, DEC-710). A practitioner who has never saved starts from the rule book's defaults.
export default async function ExecSetupPage() {
  const session = await getSession();
  if (!session || (session.role !== 'exec' && session.role !== 'lead')) redirect('/sign-in');
  let initial = DEFAULT_ALERT_PREFERENCES;
  try {
    initial = (await readAlertPreferences(session)).preferences;
  } catch {
    // The defaults are shown; the save will reach the back end again.
  }
  const leaders = await readLeaders(session);
  return (
    <main>
      <SetupFlow initial={initial} leaders={leaders} />
    </main>
  );
}
