import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { QueueList } from '@/components/clinical/QueueList';
import { getSession } from '@/lib/auth/session';

export const metadata: Metadata = { title: 'Requests - DIUCS capacity' };
export const dynamic = 'force-dynamic';

// The queue (W44). The list refreshes in the browser; the page holds no request itself.
export default async function ClinicalQueuePage() {
  const session = await getSession();
  if (!session || session.role !== 'clinical') redirect('/sign-in');
  return (
    <main>
      <QueueList />
    </main>
  );
}
