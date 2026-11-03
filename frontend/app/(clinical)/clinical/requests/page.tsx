import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { QueueList } from '@/components/clinical/QueueList';
import { getSession } from '@/lib/auth/session';
import { readPresence } from '@/lib/clinical/clinicalServer';

export const metadata: Metadata = { title: 'Requests - Overwatch' };
export const dynamic = 'force-dynamic';

const PRESENCE_WORDS = { available: 'Available', busy: 'Busy', away: 'Away' } as const;

// The queue (W44). The list refreshes in the browser; the page holds no request itself. The advisor's own
// status is read from the back end's presence; a read that fails shows no status, never a wrong one.
export default async function ClinicalQueuePage() {
  const session = await getSession();
  if (!session || session.role !== 'clinical') redirect('/sign-in');
  const presence = await readPresence(session).then((own) => own.presence).catch(() => null);
  return (
    <main>
      <QueueList status={presence === null ? null : PRESENCE_WORDS[presence]} />
    </main>
  );
}
