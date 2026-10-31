import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { CaseView } from '@/components/clinical/CaseView';
import { getSession } from '@/lib/auth/session';
import { readRequest, readSeen } from '@/lib/clinical/clinicalServer';

export const metadata: Metadata = { title: 'Case - DIUCS capacity' };
export const dynamic = 'force-dynamic';

const ID = /^[A-Za-z0-9-]{1,64}$/;

// The taken request, read from the back end by its id alone (DEC-774). A read that fails gives the screen
// no request, and the screen then offers no advice form (DEC-855). What the advisor saw is its own read (W9G),
// asked for only on a request someone holds or advised (a waiting request is nobody's to read it); a read that
// fails gives the screen none, and it says so.
export default async function ClinicalCasePage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || session.role !== 'clinical') redirect('/sign-in');
  const { id } = await params;
  if (!ID.test(id)) redirect('/clinical/requests');
  const request = await readRequest(session, id).catch(() => null);
  const seen = request !== null && request.glance !== null && request.status !== 'requested' ? await readSeen(session, id).catch(() => null) : null;
  return (
    <main>
      <CaseView requestId={id} request={request} seen={seen} />
    </main>
  );
}
