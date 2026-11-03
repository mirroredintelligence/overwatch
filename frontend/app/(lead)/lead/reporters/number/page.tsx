import type { Metadata } from 'next';
import { ChangeNumberForm } from '@/components/lead/ChangeNumberForm';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// Change reporter number (W18; INV-03). At /lead/reporters/number, with ?service=<id> to choose the service:
// the reporters page with that service's "Change their number" row open.

export const metadata: Metadata = {
  title: 'Change reporter number - Overwatch',
  robots: { index: false },
};

export default async function ChangeNumberPage({
  searchParams,
}: {
  searchParams: Promise<{ service?: string | string[] }>;
}) {
  const { service } = await searchParams;
  const serviceId = typeof service === 'string' && SERVICE_ID.test(service) ? service : undefined;
  return <ChangeNumberForm serviceId={serviceId} />;
}
