import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import { AlertDetail } from '@/components/exec/AlertDetail';
import { AttentionRail, PlanningStage } from '@/components/exec/PlanningStage';
import { ServiceDetail } from '@/components/exec/ServiceDetail';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import { ALERT_ROLES, alertsByState } from '@/lib/exec/alertsServer';
import type { AlertItem } from '@/lib/exec/alerts';
import { needsAttention } from '@/lib/exec/homeSummary';
import { hasDeputy } from '@/lib/exec/savePreferences';
import { readAlertPreferences } from '@/lib/exec/subscriptions';

export const metadata: Metadata = { title: 'Alert - Overwatch' };
export const dynamic = 'force-dynamic';

// An alert is read from the caller's own lists (open, then acknowledged, then closed): the back end has no
// single-alert read. The duty coordinator's number is the board's (DEC-777), or none. The alert opens in place
// beside its service (the planning stage at its alert state); when the board cannot be read, or has no such
// service, the alert stands alone with no number.
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
  const board = await readBoard(session).catch(() => null);
  const phone = board?.coordinationPhone ?? null;
  const entry = board?.entries.find((item) => item.serviceId === alert.serviceId);
  if (!board || !entry) {
    return (
      <main>
        <AlertDetail alert={alert} coordinationPhone={phone} />
      </main>
    );
  }
  let escalationInPlace: boolean | undefined;
  try {
    escalationInPlace = hasDeputy((await readAlertPreferences(session)).preferences);
  } catch {
    escalationInPlace = undefined;
  }
  const counts: Record<string, number> = {};
  for (const item of board.entries) counts[item.status] = (counts[item.status] ?? 0) + 1;
  return (
    <main>
      <PlanningStage
        stage="alert"
        counts={counts}
        rail={<AttentionRail entries={needsAttention(board)} currentId={entry.serviceId} />}
        service={<ServiceDetail entry={entry} now={board.generatedAt} coordinationPhone={phone} alert={alert} escalationInPlace={escalationInPlace} />}
        sideAlert={<AlertDetail alert={alert} coordinationPhone={phone} />}
      />
    </main>
  );
}
