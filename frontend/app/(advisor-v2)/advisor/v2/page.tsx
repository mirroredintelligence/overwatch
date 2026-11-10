import type { Metadata } from 'next';
import { Suspense } from 'react';
import { CapacityOverview } from '@/components/advisor-v2/CapacityOverview';
import { V2Switch } from '@/components/advisor-v2/V2Switch';
import { AdvisorWorkspace } from '@/components/workspace/AdvisorWorkspace';
import { WorkspacePage } from '@/components/workspace/WorkspacePage';

export const metadata: Metadata = {
  title: 'Advisor v2 · Overwatch',
};

// The Advisor v2 pages (DEC-1362, DEC-1366, DEC-1376, WS-RTE): Capacity (the default) runs in the workspace frame with the
// switch to Find a Service; mode=find is the find workspace, which supplies its own frame. Browse only: no case is opened
// and nothing is stored. The proxy guard (lib/auth/access.ts) opens `/advisor/v2` to the advisor and to Advisor v2. It sits
// in its own route group so it does not carry the v1 booking-alert strip, whose reads Advisor v2 does not hold.
export default async function AdvisorV2Page({ searchParams }: { searchParams: Promise<{ mode?: string | string[] }> }) {
  const { mode } = await searchParams;
  if (mode === 'find') {
    return (
      <Suspense fallback={null}>
        <AdvisorWorkspace />
      </Suspense>
    );
  }
  return (
    <WorkspacePage title="Capacity" withThread={false}>
      <V2Switch current="capacity" />
      <CapacityOverview />
    </WorkspacePage>
  );
}
