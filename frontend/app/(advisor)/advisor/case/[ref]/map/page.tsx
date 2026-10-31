import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { MapScreen } from '@/components/advisor/MapScreen';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';

export const metadata: Metadata = {
  title: 'Map · Overwatch',
};

// The map view of the options (URL /advisor/case/[ref]/map). The same services as the list, drawn.
// The page holds no case data; the screen reads it through the BFF.
export default async function CaseMapPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="options" />
      <OwnScopeHeader ownHref={`/advisor/case/${encodeURIComponent(ref)}/map`} networkHref={`/advisor/case/${encodeURIComponent(ref)}/network-map`} />
      <MapScreen caseId={ref} />
    </main>
  );
}
