import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { FinishScreen } from '@/components/advisor/FinishScreen';
import { outcomeFromAddress } from '@/lib/advisor/outcome';

export const metadata: Metadata = {
  title: 'Record outcome · Overwatch',
};

// The outcome step (URL /advisor/case/[ref]/finish). The address may name the outcome to preselect
// (`?outcome=no-service-fits`); an unknown value is ignored. `?closed=1` is the closed state: the call
// steps are not shown after the case is closed.
export default async function CaseFinishPage({
  params,
  searchParams,
}: {
  params: Promise<{ ref: string }>;
  searchParams: Promise<{ outcome?: string | string[]; closed?: string | string[] }>;
}) {
  const { ref } = await params;
  const query = await searchParams;
  const preselect = outcomeFromAddress(Array.isArray(query.outcome) ? undefined : query.outcome);
  const closed = query.closed === '1';
  return (
    <main>
      {closed ? null : <CallSteps current="outcome" />}
      <FinishScreen caseId={ref} preselect={preselect} closed={closed} />
    </main>
  );
}
