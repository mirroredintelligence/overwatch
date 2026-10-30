import type { Metadata } from 'next';
import { ChangeNumberForm } from '@/components/lead/ChangeNumberForm';

// Change reporter number (W18). At /lead/reporters/number, with ?service=<id> to choose the service.

export const metadata: Metadata = {
  title: 'Change reporter number - DIUCS capacity',
  robots: { index: false },
};

const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;

export default async function ChangeNumberPage({
  searchParams,
}: {
  searchParams: Promise<{ service?: string | string[] }>;
}) {
  const { service } = await searchParams;
  const serviceId = typeof service === 'string' && SERVICE_ID.test(service) ? service : undefined;
  return <ChangeNumberForm serviceId={serviceId} />;
}
