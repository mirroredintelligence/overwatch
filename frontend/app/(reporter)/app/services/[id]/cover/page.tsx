import { ServiceCover } from '@/components/reporter/multi/ServiceCover';

export const dynamic = 'force-dynamic';

export default async function CoverPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ServiceCover serviceId={id} serviceName="this service" />;
}
