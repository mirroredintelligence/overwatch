import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { MapScreen } from '@/components/advisor/MapScreen';

export const metadata: Metadata = {
  title: 'Map · DIUCS capacity',
};

// The map view of the options (URL /advisor/case/[ref]/map). The same services as the list, drawn.
// The page holds no case data; the screen reads it through the BFF.
export default async function CaseMapPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <MapScreen caseId={ref} />
    </main>
  );
}
