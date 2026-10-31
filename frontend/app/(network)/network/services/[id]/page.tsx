import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkServiceDetail } from '@/components/network/NetworkServiceDetail';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// One service of the network (TEN-071): at /network/services/<row reference>. The reference is the opaque
// one the back end gave the row; it names no tenant, organisation or service of an organisation.

export const metadata: Metadata = { title: 'Network service', robots: { index: false } };
export const dynamic = 'force-dynamic';

const ROW_REF = /^[A-Za-z0-9._-]{1,64}$/;

export default async function NetworkServicePage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/services')) redirect('/sign-in');
  const { id } = await params;
  // A reference that cannot be one is the same panel as one that is not there.
  return <NetworkServiceDetail rowRef={ROW_REF.test(id) ? id : ''} ownHref={ownHrefFor('services', session.role)} />;
}
