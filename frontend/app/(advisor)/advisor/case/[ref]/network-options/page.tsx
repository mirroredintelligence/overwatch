import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { CaseSummary } from '@/components/advisor/CaseSummary';
import { NetworkOptions } from '@/components/advisor/NetworkOptions';

export const metadata: Metadata = {
  title: 'Network options · DIUCS capacity',
  robots: { index: false },
};

// The options step of a call, in the network (URL /advisor/case/[ref]/network-options; WB11): the services of
// the other organisations in the network that meet the case's criteria, read only. The page passes only the
// case's reference. The network the advisor looks at is chosen in the page from the networks the server
// offers, never in the address, and the case's postcode, age and needs are read by the back end in the
// advisor's own organisation and never sent from here.
export default async function CaseNetworkOptionsPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <CaseSummary caseId={ref} />
      <NetworkOptions caseId={ref} />
    </main>
  );
}
