import type { Metadata } from 'next';
import { ServicesBrowse } from '@/components/advisor/ServicesBrowse';
import { statusesFromQuery } from '@/lib/advisor/servicesBrowse';

export const metadata: Metadata = {
  title: 'Services · Overwatch',
};

// The services by state (URL /advisor/services, optionally ?status=accepting,limited), opened from the counts on the
// advisor home (DEC-1343). The proxy guard already limits /advisor to advisors.
export default async function AdvisorServicesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string | string[] }>;
}) {
  const query = await searchParams;
  return (
    <main>
      <h1>Services</h1>
      <ServicesBrowse initial={statusesFromQuery(query.status)} />
    </main>
  );
}
