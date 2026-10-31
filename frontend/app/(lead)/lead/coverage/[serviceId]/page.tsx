import type { Metadata } from 'next';
import { CoverageForm } from '@/components/areas/CoverageForm';

// Define a coverage area (RadarWeb 5), at /lead/coverage/<service>. The page holds no service data; the form
// reads and saves through the BFF.

export const metadata: Metadata = {
  title: 'Define a coverage area · Overwatch',
  robots: { index: false },
};

export default async function CoveragePage({ params }: { params: Promise<{ serviceId: string }> }) {
  const { serviceId } = await params;
  return <CoverageForm serviceId={serviceId} />;
}
