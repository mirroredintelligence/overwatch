import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkSystemNowView } from '@/components/network/NetworkSystemNowView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// The network variant of the shift lead's System now (W17, TEN-070): at /network/system-now. Read only. The page takes no input; the networks the viewer may see are read from the
// BFF per call, and the address names no tenant, network or scope.

export const metadata: Metadata = { title: 'Network system now', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkSystemNowPage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/system-now')) redirect('/sign-in');
  return <NetworkSystemNowView ownHref={ownHrefFor('system-now', session.role)} />;
}
