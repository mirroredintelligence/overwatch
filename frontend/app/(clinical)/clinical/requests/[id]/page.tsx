import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { CaseView } from '@/components/clinical/CaseView';
import { getSession } from '@/lib/auth/session';
import { REQUEST_URGENCIES, REQUEST_WHYS } from '@/lib/clinical/advice';

export const metadata: Metadata = { title: 'Case - DIUCS capacity' };
export const dynamic = 'force-dynamic';

const ID = /^[A-Za-z0-9-]{1,64}$/;
const CASE = /^case-[A-Za-z0-9-]{1,40}$/;

// The taken request. Its queue context (urgency, reason, case number) comes from the queue's link, which
// names nothing but those; each value is checked against the back end's own list before it is shown.
export default async function ClinicalCasePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ urgency?: string; why?: string; case?: string }>;
}) {
  const session = await getSession();
  if (!session || session.role !== 'clinical') redirect('/sign-in');
  const { id } = await params;
  if (!ID.test(id)) redirect('/clinical/requests');
  const query = await searchParams;
  const urgency = (REQUEST_URGENCIES as readonly string[]).includes(query.urgency ?? '') ? query.urgency : 'within-15-min';
  const why = (REQUEST_WHYS as readonly string[]).includes(query.why ?? '') ? query.why : 'other';
  const caseId = query.case !== undefined && CASE.test(query.case) ? query.case : `case-${id}`;
  return (
    <main>
      <CaseView request={{ id, urgency: urgency as 'now' | 'within-15-min', why: why as string, caseId }} />
    </main>
  );
}
