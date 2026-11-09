import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { ScreenForm } from '@/components/screens/ScreenForm';
import { getSession } from '@/lib/auth/session';
import { tenantLetters } from '@/lib/tenant/hint';

export const metadata: Metadata = {
  title: 'Add a wall screen - Overwatch',
  robots: { index: false },
};

export const dynamic = 'force-dynamic';

// The lead page for connecting a wall display. The proxy already keeps every other role out of
// /lead; this checks again, so a change to the guard cannot open the page, and the BFF route it posts
// to checks the role a third time. The page takes no input. It tells the lead which address to open on the display: the
// one shared host with the lead's own organisation in it (DEC-1354).
export default async function AddWallScreenPage() {
  const session = await getSession();
  if (session?.role !== 'lead') redirect('/sign-in?next=%2Flead%2Fscreens%2Fnew');
  const letters = tenantLetters(session.tenantId);
  const pairAddress = letters !== null ? `https://${session.host}/screen/pair?org=${letters}` : null;
  return <ScreenForm pairAddress={pairAddress} />;
}
