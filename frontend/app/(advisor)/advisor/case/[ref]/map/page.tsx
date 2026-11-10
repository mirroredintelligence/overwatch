import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { MapScreen } from '@/components/advisor/MapScreen';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';

export const metadata: Metadata = {
  title: 'Map · Overwatch',
};

// The map view of the options (URL /advisor/case/[ref]/map). The same services as the list, drawn.
// The page holds no case data; the screen reads it through the BFF. `?layer=coverage` opens it with the "Who covers
// this area" layer on: the old Radar address redirects there (DEC-1372).
export default async function CaseMapPage({
  params,
  searchParams,
}: {
  params: Promise<{ ref: string }>;
  searchParams: Promise<{ layer?: string | string[] }>;
}) {
  const { ref } = await params;
  const { layer } = await searchParams;
  return (
    <main>
      <CallSteps current="options" />
      <OwnScopeHeader ownHref={`/advisor/case/${encodeURIComponent(ref)}/map`} networkHref={`/advisor/case/${encodeURIComponent(ref)}/network-map`} />
      <MapScreen caseId={ref} initialCoverage={layer === 'coverage'} />
    </main>
  );
}
