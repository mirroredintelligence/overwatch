import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkWeekView } from '@/components/network/NetworkWeekView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';
import { NETWORK_WEEK_ROLES } from '@/lib/network/availability';

// The network's week summary (TEN-082): at /network/week. Read only. The page takes no input; the networks the viewer may see are read from the
// BFF per call, and the address names no tenant, network or scope.

export const metadata: Metadata = { title: 'Network week', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkWeekPage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/week')) redirect('/sign-in');
  // Only the executive and the shift lead read the week (the back end refuses the others too).
  if (!(NETWORK_WEEK_ROLES as readonly string[]).includes(session.role)) redirect('/forbidden');
  return <NetworkWeekView ownHref={ownHrefFor('week', session.role)} />;
}
