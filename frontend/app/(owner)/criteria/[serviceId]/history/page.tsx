import type { Metadata } from 'next';
import { CriteriaHistory } from '@/components/owner/CriteriaHistory';

export const metadata: Metadata = {
  title: 'Criteria history · DIUCS capacity',
};

export const dynamic = 'force-dynamic';

export default async function HistoryPage({ params }: { params: Promise<{ serviceId: string }> }) {
  const { serviceId } = await params;
  return <CriteriaHistory serviceId={serviceId} />;
}
