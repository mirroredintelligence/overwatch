import type { Metadata } from 'next';
import { ServiceDetail } from '@/components/service/ServiceDetail';

export const metadata: Metadata = {
  title: 'Service · Advisor v2 · Overwatch',
};

// The advisor's service detail page (DEC-1367): the shared page, for the advisor and for Advisor v2 (the proxy guard,
// lib/auth/access.ts, opens `/advisor/v2/**` to both). It links back to the finder.
export default async function AdvisorV2ServicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ServiceDetail serviceId={id} backHref="/advisor/v2" backLabel="Back to the finder" rootLabel="Find a service" />;
}
