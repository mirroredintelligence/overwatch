import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { ScreenForm } from '@/components/screens/ScreenForm';
import { getSession } from '@/lib/auth/session';

export const metadata: Metadata = {
  title: 'Add a wall screen - DIUCS capacity',
  robots: { index: false },
};

export const dynamic = 'force-dynamic';

// The lead page for connecting a wall display. The proxy already keeps every other role out of
// /lead; this checks again, so a change to the guard cannot open the page, and the BFF route it posts
// to checks the role a third time. The page takes no input.
export default async function AddWallScreenPage() {
  const session = await getSession();
  if (session?.role !== 'lead') redirect('/sign-in?next=%2Flead%2Fscreens%2Fnew');
  return <ScreenForm />;
}
