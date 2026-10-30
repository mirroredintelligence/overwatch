import type { Metadata } from 'next';
import { CriteriaApproval } from '@/components/owner/CriteriaApproval';

export const metadata: Metadata = {
  title: 'Second approval · DIUCS capacity',
};

export const dynamic = 'force-dynamic';

// The clinical lead's second approval of a criteria change (W31). The page takes no input beyond the
// service in its address; who may approve is decided by the back end, per call.
export default async function ApprovePage({ params }: { params: Promise<{ serviceId: string }> }) {
  const { serviceId } = await params;
  return <CriteriaApproval serviceId={serviceId} />;
}
