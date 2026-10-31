import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { WeekSummary } from '@/components/exec/WeekSummary';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import { Banner } from '@/components/ui/Banner';
import { getSession } from '@/lib/auth/session';
import { type AlertPreferences } from '@/lib/exec/alertPrefs';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';
import { readAlertPreferences } from '@/lib/exec/subscriptions';
import { readWeekSummary } from '@/lib/exec/weekServer';
import { weekEndingDefault, type WeekSummary as Summary } from '@/lib/exec/weekSummary';

export const metadata: Metadata = { title: 'This week - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// The last complete week (W41). The Monday switch needs the executive's preferences; when they cannot be
// read the figures still show, and the switch does not.
export default async function ExecWeekPage() {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  let summary: Summary | null = null;
  try {
    summary = await readWeekSummary(session, weekEndingDefault(new Date()));
  } catch {
    summary = null;
  }
  let prefs: AlertPreferences | null = null;
  try {
    prefs = (await readAlertPreferences(session)).preferences;
  } catch {
    prefs = null;
  }
  if (summary === null) {
    return (
      <main>
        <Banner tone="offline" title="This week could not be read. Try again shortly." />
      </main>
    );
  }
  return (
    <main>
      {/* Which board this is (TEN-069), with the way to the network's week when there is one (TEN-082). */}
      <OwnScopeHeader ownHref="/planning/week" networkHref="/network/week" />
      <WeekSummary summary={summary} prefs={prefs} />
    </main>
  );
}
