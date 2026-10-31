import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import { ServiceDetail } from '@/components/exec/ServiceDetail';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import type { AlertItem } from '@/lib/exec/alerts';
import { ALERT_ROLES, alertsByState } from '@/lib/exec/alertsServer';
import { hasDeputy } from '@/lib/exec/savePreferences';
import { readAlertPreferences } from '@/lib/exec/subscriptions';

export const metadata: Metadata = { title: 'Service - Overwatch' };
export const dynamic = 'force-dynamic';

export default async function ExecServicePage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  const { id } = await params;
  const board = await readBoard(session);
  const entry = board.entries.find((item) => item.serviceId === id);
  if (!entry) notFound();
  // The alert row and the escalation row (ExecApp1 screen 2) are the executive's own, read with their token.
  // Either that cannot be read is left out of the screen: no row is made up.
  let alert: AlertItem | null | undefined;
  try {
    const [open, acknowledged] = await Promise.all([alertsByState(session, 'open'), alertsByState(session, 'acknowledged')]);
    const mine = [...open, ...acknowledged].filter((item) => item.serviceId === id);
    mine.sort((a, b) => b.raisedAt.localeCompare(a.raisedAt));
    alert = mine[0] ?? null;
  } catch {
    alert = undefined;
  }
  let escalationInPlace: boolean | undefined;
  try {
    escalationInPlace = hasDeputy((await readAlertPreferences(session)).preferences);
  } catch {
    escalationInPlace = undefined;
  }
  return (
    <main>
      {/* The network's variant of a service is its own page, with no alert subscription (WB11). */}
      {session.role === 'exec' ? <OwnScopeHeader ownHref={`/planning/services/${encodeURIComponent(id)}`} networkHref="/network/services" /> : <ScopeHeader scope="own" />}
      <ServiceDetail entry={entry} now={board.generatedAt} coordinationPhone={board.coordinationPhone ?? null} alert={alert} escalationInPlace={escalationInPlace} />
    </main>
  );
}
