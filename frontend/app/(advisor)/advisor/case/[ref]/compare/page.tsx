import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { CompareScreen } from '@/components/radar/CompareScreen';

export const metadata: Metadata = {
  title: 'Compare covering services · Overwatch',
};

// Compare the covering services (URL /advisor/case/[ref]/compare). The page holds no case data; the screen
// reads the case's options through the BFF, the same read as the map and the list.
export default async function CaseComparePage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <CompareScreen caseId={ref} />
    </main>
  );
}
