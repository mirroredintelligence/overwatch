import type { Metadata } from 'next';
import { ServiceWorkspace } from '@/components/workspace/ServiceWorkspace';

export const metadata: Metadata = {
  title: 'Service · Advisor v2 · Overwatch',
};

// The advisor's service detail page (DEC-1367, DEC-1376): the shared service detail inside the workspace frame, for the
// advisor and for Advisor v2 (the proxy guard, lib/auth/access.ts, opens `/advisor/v2/**` to both). It links back to the
// results. The client component reads the opened service and the thread from the workspace provider.
export default async function AdvisorV2ServicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ServiceWorkspace serviceId={id} />;
}
