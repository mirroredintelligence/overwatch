import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { RadarScreen } from '@/components/radar/RadarScreen';

export const metadata: Metadata = {
  title: 'Who covers this area · Overwatch',
};

// Radar: who covers this area (URL /advisor/case/[ref]/radar). The page holds no case data; the screen
// reads the case's options through the BFF, the same read as the map and the list.
export default async function CaseRadarPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <RadarScreen caseId={ref} />
    </main>
  );
}
