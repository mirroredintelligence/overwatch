import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { CaseSummary } from '@/components/advisor/CaseSummary';
import { OptionsList } from '@/components/advisor/OptionsList';
import styles from '@/components/advisor/Advisor.module.css';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';

export const metadata: Metadata = {
  title: 'Options · Overwatch',
};

// The options step of a call (URL /advisor/case/[ref]/options). The list reads the options itself,
// once per load; the page passes only the case id, since a server page cannot pass handlers.
export default async function CaseOptionsPage({
  params,
  searchParams,
}: {
  params: Promise<{ ref: string }>;
  searchParams?: Promise<{ service?: string | string[] }>;
}) {
  const { ref } = await params;
  // ?service=[id] opens that service's Request state; the list ignores an id that is not among this case's options.
  const asked = (await searchParams)?.service;
  const service = (Array.isArray(asked) ? asked[0] : asked) || null;
  return (
    <main>
      {/* The page's one level-one heading: the steps and the list below carry the visible words. */}
      <h1 className={styles.visuallyHidden}>Options for this call</h1>
      <CallSteps current="options" />
      <CaseSummary caseId={ref} />
      {/* Which board this is, and the way to the network's options when the organisation is in one (WB11). */}
      <OwnScopeHeader ownHref={`/advisor/case/${encodeURIComponent(ref)}/options`} networkHref={`/advisor/case/${encodeURIComponent(ref)}/network-options`} />
      <OptionsList caseId={ref} serviceId={service} />
    </main>
  );
}
