import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { PairingScreen } from '@/components/screens/PairingScreen';
import { getSession } from '@/lib/auth/session';

export const metadata: Metadata = {
  title: 'Overwatch wall screen',
  // A wall display is not for search engines or caches.
  robots: { index: false },
};

// Read at every request: it depends on this display's own cookies.
export const dynamic = 'force-dynamic';

// The page a wall display opens, with nobody signed in. It takes no code or screen from the address; the
// organisation's letters in `?org=` (DEC-1354) only say where its pairing is made, and the browser reads them. A display that already has a wall
// session goes straight to the board; a staff session is not a paired screen.
export default async function WallPairPage() {
  const session = await getSession();
  if (session?.role === 'wall') redirect('/screen');
  return <PairingScreen />;
}
