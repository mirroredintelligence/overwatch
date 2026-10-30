import { AddedService } from '@/components/reporter/multi/AddedService';

export const dynamic = 'force-dynamic';

// The service's name comes from the services list the page reads; until then the page names it as
// the one the lead added (the list carries the name, so the link passes only the id).
export default async function AddedPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AddedService serviceId={id} serviceName="your new service" />;
}
