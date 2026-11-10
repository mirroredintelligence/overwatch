import type { Metadata } from 'next';
import { V2Services } from '@/components/advisor-v2/V2Services';
import { groupFromQuery, statusesFromQuery } from '@/lib/advisor/v2/overview';

export const metadata: Metadata = {
  title: 'Services · Advisor v2 · Overwatch',
};

// The services by state under Advisor v2 (URL /advisor/v2/services, optionally ?status=accepting,limited), opened from
// the counts on Capacity (DEC-1366). Each service links to /advisor/v2/services/<id>, a page built on its own.
export default async function AdvisorV2ServicesPage({ searchParams }: { searchParams: Promise<{ status?: string | string[]; group?: string | string[] }> }) {
  const query = await searchParams;
  return (
    <main>
      <h1>Services</h1>
      <V2Services initial={statusesFromQuery(query.status)} group={groupFromQuery(query.group)} />
    </main>
  );
}
