import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { NetworkMap } from '@/components/advisor/NetworkMap';

export const metadata: Metadata = {
  title: 'Network map · Overwatch',
  robots: { index: false },
};

// The map of the network's options (URL /advisor/case/[ref]/network-map; WB11): the same services as the
// network list, drawn, read only. The page holds no case data; the screen reads the options through the BFF
// with the case's reference only.
export default async function CaseNetworkMapPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <NetworkMap caseId={ref} />
    </main>
  );
}
