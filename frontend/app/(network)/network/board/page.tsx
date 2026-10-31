import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkBoardView } from '@/components/network/NetworkBoardView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// The network capacity board (TEN-070): at /network/board, the network variant of the viewer's own board.
// The page takes no input; the networks the viewer may see are read from the BFF, per call, and the page
// names no tenant, network or scope in its address.

export const metadata: Metadata = { title: 'Network capacity', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkBoardPage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/board')) redirect('/sign-in');
  return <NetworkBoardView ownHref={ownHrefFor('board', session.role)} />;
}
