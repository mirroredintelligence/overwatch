import type { Metadata } from 'next';
import { MoveServiceForm } from '@/components/lead/MoveServiceForm';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// Move a service to another phone (W43). At /lead/phones/move, with ?service=<id> to choose the service.

export const metadata: Metadata = {
  title: 'Move a service - DIUCS capacity',
  robots: { index: false },
};

export default async function MovePage({ searchParams }: { searchParams: Promise<{ service?: string | string[] }> }) {
  const { service } = await searchParams;
  return <MoveServiceForm serviceId={typeof service === 'string' && SERVICE_ID.test(service) ? service : undefined} />;
}
