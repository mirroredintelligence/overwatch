import type { Metadata } from 'next';
import { CapacityOverview } from '@/components/advisor-v2/CapacityOverview';
import { FindService } from '@/components/advisor-v2/FindService';
import { V2Switch, type V2Mode } from '@/components/advisor-v2/V2Switch';

export const metadata: Metadata = {
  title: 'Advisor v2 · Overwatch',
};

// The Advisor v2 pages (DEC-1362, DEC-1366): a switch between Capacity (the default) and Find a Service. Browse only:
// no case is opened and nothing is stored. The proxy guard (lib/auth/access.ts) opens `/advisor/v2` to the advisor
// and to Advisor v2. It sits in its own route group so it does not carry the v1 booking-alert strip, whose reads
// Advisor v2 does not hold.
export default async function AdvisorV2Page({ searchParams }: { searchParams: Promise<{ mode?: string | string[] }> }) {
  const { mode } = await searchParams;
  const current: V2Mode = mode === 'find' ? 'find' : 'capacity';
  return (
    <main>
      <h1>Advisor v2</h1>
      <V2Switch current={current} />
      {current === 'find' ? <FindService /> : <CapacityOverview />}
    </main>
  );
}
