import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkHomeView } from '@/components/network/NetworkHomeView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// The network variant of the advisor's home and of the executive's home (WB11, W10-K3): at /network/home, the
// counts of the network's rows with the scope header. Read only. The page takes no input; the networks the
// viewer may see are read from the BFF per call, and the address names no tenant, network or scope.

export const metadata: Metadata = { title: 'Network home', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkHomePage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/home')) redirect('/sign-in');
  // The two homes that count the board: the advisor's and the executive's. The others have no home counts.
  if (session.role !== 'advisor' && session.role !== 'exec') redirect('/sign-in');
  return <NetworkHomeView audience={session.role} ownHref={ownHrefFor('home', session.role)} />;
}
