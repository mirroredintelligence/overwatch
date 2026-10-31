import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { ScreenList } from '@/components/lead/ScreenList';
import { getSession } from '@/lib/auth/session';

export const metadata: Metadata = {
  title: 'Wall screens - DIUCS capacity',
  robots: { index: false },
};

export const dynamic = 'force-dynamic';

// The shift lead's list of the organisation's wall screens, with the way to disconnect one (W9I,
// TEN-072). At /lead/screens. The proxy already keeps every other role out of /lead; this checks again,
// so a change to the guard cannot open the page, and the BFF routes it calls check the role a third
// time. The page takes no input.
export default async function WallScreensPage() {
  const session = await getSession();
  if (session?.role !== 'lead') redirect('/sign-in?next=%2Flead%2Fscreens');
  return <ScreenList />;
}
