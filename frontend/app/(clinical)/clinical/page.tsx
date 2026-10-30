import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { DutyForm } from '@/components/clinical/DutyForm';
import { getSession } from '@/lib/auth/session';
import { readAvailable, readQueue } from '@/lib/clinical/clinicalServer';

export const metadata: Metadata = { title: 'On duty - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// The clinical advisor's on-duty page (W44). The counts are the back end's; the page holds no name.
export default async function ClinicalDutyPage() {
  const session = await getSession();
  if (!session || session.role !== 'clinical') redirect('/sign-in');
  const [available, waiting] = await Promise.all([
    readAvailable(session).catch(() => 0),
    readQueue(session).then((items) => items.length).catch(() => 0),
  ]);
  return (
    <main>
      <DutyForm available={available} waiting={waiting} />
    </main>
  );
}
