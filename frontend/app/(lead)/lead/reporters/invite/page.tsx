import type { Metadata } from 'next';
import { InviteForm } from '@/components/lead/InviteForm';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// Invite a reporter (W43). At /lead/reporters/invite, with ?service=<id> to prefill the service.

export const metadata: Metadata = {
  title: 'Invite a reporter - DIUCS capacity',
  robots: { index: false },
};

export default async function InvitePage({ searchParams }: { searchParams: Promise<{ service?: string | string[] }> }) {
  const { service } = await searchParams;
  return <InviteForm serviceId={typeof service === 'string' && SERVICE_ID.test(service) ? service : undefined} />;
}
