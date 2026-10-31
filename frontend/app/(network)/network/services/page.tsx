import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkServicesView } from '@/components/network/NetworkServicesView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// The network directory (TEN-071): at /network/services. Read only.

export const metadata: Metadata = { title: 'Network services', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkServicesPage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/services')) redirect('/sign-in');
  return <NetworkServicesView ownHref={ownHrefFor('services', session.role)} />;
}
