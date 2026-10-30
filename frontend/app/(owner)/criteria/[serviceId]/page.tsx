import type { Metadata } from 'next';
import { CriteriaFlow } from '@/components/owner/CriteriaFlow';
import type { CriteriaStep } from '@/lib/criteria/types';

export const metadata: Metadata = {
  title: 'Criteria · DIUCS capacity',
};

export const dynamic = 'force-dynamic';

const STEPS: readonly CriteriaStep[] = ['overview', 'confirm', 'edit', 'preview', 'send'];

// The owner's criteria for one service (W30). `?step=` opens a step; the status tracker is reached
// from the send step, and an unknown or missing value shows the overview. Steps after the overview
// keep their draft in the page, so a direct link to preview or send opens the editor first.
export default async function CriteriaPage({
  params,
  searchParams,
}: {
  params: Promise<{ serviceId: string }>;
  searchParams: Promise<{ step?: string | string[] }>;
}) {
  const { serviceId } = await params;
  const { step } = await searchParams;
  const requested = typeof step === 'string' ? (step as CriteriaStep) : 'overview';
  const initial: CriteriaStep = (STEPS as readonly string[]).includes(requested) ? requested : 'overview';
  return <CriteriaFlow serviceId={serviceId} initialStep={initial} />;
}
