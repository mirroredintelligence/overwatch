import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { WaysScreen } from '@/components/radar/WaysScreen';

export const metadata: Metadata = {
  title: 'Three ways to meet the need · Overwatch',
};

// Three ways to meet the need (URL /advisor/case/[ref]/ways). The page holds no case data; the screen reads
// the case's options through the BFF, the same read as the map and the list.
export default async function CaseWaysPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <WaysScreen caseId={ref} />
    </main>
  );
}
