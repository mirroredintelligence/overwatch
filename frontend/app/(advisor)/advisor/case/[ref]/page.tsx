import type { Metadata } from 'next';
import { CallSteps } from '@/components/advisor/CallSteps';
import { NeedsForm } from '@/components/advisor/NeedsForm';

export const metadata: Metadata = {
  title: 'Patient needs · DIUCS capacity',
};

// The needs step of a call (URL /advisor/case/[ref]). The segment is the case id: the back end keys
// a case by id and does not return the four-digit reference on the FHIR ServiceRequest (see
// docs/delivery/fragments/W10.md). The page holds no case data; the form reads it through the BFF.
export default async function CaseNeedsPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return (
    <main>
      <CallSteps current="needs" />
      <NeedsForm caseId={ref} openedAt={new Date().toISOString()} />
    </main>
  );
}
