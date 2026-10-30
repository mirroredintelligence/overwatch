import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import { ServiceDetail } from '@/components/exec/ServiceDetail';
import { getSession } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';

export const metadata: Metadata = { title: 'Service - DIUCS capacity' };
export const dynamic = 'force-dynamic';

export default async function ExecServicePage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || !(ALERT_ROLES as readonly string[]).includes(session.role)) redirect('/sign-in');
  const { id } = await params;
  const board = await readBoard(session);
  const entry = board.entries.find((item) => item.serviceId === id);
  if (!entry) notFound();
  return (
    <main>
      <ServiceDetail entry={entry} now={board.generatedAt} coordinationPhone={board.coordinationPhone ?? null} />
    </main>
  );
}
