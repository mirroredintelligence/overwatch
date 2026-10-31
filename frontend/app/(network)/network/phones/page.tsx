import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkPhonesView } from '@/components/network/NetworkPhonesView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// The network variant of phones and services (W43, TEN-070): at /network/phones. Read only. The page takes no input; the networks the viewer may see are read from the
// BFF per call, and the address names no tenant, network or scope.

export const metadata: Metadata = { title: 'Network phones', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkPhonesPage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/phones')) redirect('/sign-in');
  return <NetworkPhonesView ownHref={ownHrefFor('phones', session.role)} />;
}
