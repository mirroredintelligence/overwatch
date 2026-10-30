import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { DutyForm } from '@/components/clinical/DutyForm';
import { getSession } from '@/lib/auth/session';
import { readPresence, readQueue } from '@/lib/clinical/clinicalServer';

export const metadata: Metadata = { title: 'On duty - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// The clinical advisor's on-duty page (W44). The presence and the counts are the back end's; the page holds
// no name. A read that fails is shown as unread, never as zero.
export default async function ClinicalDutyPage() {
  const session = await getSession();
  if (!session || session.role !== 'clinical') redirect('/sign-in');
  const [presence, waiting] = await Promise.all([
    readPresence(session).catch(() => null),
    readQueue(session).then((items) => items.length).catch(() => null),
  ]);
  return (
    <main>
      <DutyForm available={presence?.available ?? null} waiting={waiting} presence={presence?.presence ?? null} />
    </main>
  );
}
