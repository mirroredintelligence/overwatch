import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { NetworkHistoryView } from '@/components/network/NetworkHistoryView';
import { canAccess } from '@/lib/auth/access';
import { getSession } from '@/lib/auth/session';
import { ownHrefFor } from '@/lib/network/links';

// What members that left or stopped sharing had shared (TEN-070): at /network/history. Read only.

export const metadata: Metadata = { title: 'Network history', robots: { index: false } };
export const dynamic = 'force-dynamic';

export default async function NetworkHistoryPage() {
  const session = await getSession();
  if (!session || !canAccess(session.role, '/network/history')) redirect('/sign-in');
  return <NetworkHistoryView ownHref={ownHrefFor('history', session.role)} />;
}
