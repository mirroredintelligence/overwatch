import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { CaseSummary } from '@/components/advisor/CaseSummary';
import { OptionsList } from '@/components/advisor/OptionsList';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';

export const metadata: Metadata = {
  title: 'Options · Overwatch',
};

// The options step of a call (URL /advisor/case/[ref]/options). The list reads the options itself,
// once per load; the page passes only the case id, since a server page cannot pass handlers.
export default async function CaseOptionsPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <CaseSummary caseId={ref} />
      {/* Which board this is, and the way to the network's options when the organisation is in one (WB11). */}
      <OwnScopeHeader ownHref={`/advisor/case/${encodeURIComponent(ref)}/options`} networkHref={`/advisor/case/${encodeURIComponent(ref)}/network-options`} />
      <OptionsList caseId={ref} />
    </main>
  );
}
