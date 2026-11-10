import type { Metadata } from 'next';
import { ServiceDetail } from '@/components/service/ServiceDetail';

export const metadata: Metadata = {
  title: 'Service · Analytics · Overwatch',
};

// The Analytics User's service detail page (DEC-1367): the shared page. The proxy guard (lib/auth/access.ts) limits
// `/analytics/**` to the role `analytics-user`; the read behind it holds no case, patient, postcode or personal data.
export default async function AnalyticsServicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ServiceDetail serviceId={id} backHref="/analytics" backLabel="Back to the overview" />;
}
