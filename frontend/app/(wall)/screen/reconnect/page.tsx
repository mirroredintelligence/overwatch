import type { Metadata } from 'next';
import { PairingScreen } from '@/components/screens/PairingScreen';

export const metadata: Metadata = {
  title: 'DIUCS capacity wall screen',
  // A wall display is not for search engines or caches.
  robots: { index: false },
};

// Read at every request: it depends on this display's own cookies.
export const dynamic = 'force-dynamic';

// Where the board sends a display whose wall session the back end no longer accepts (W9I): a lead has
// disconnected the screen, or the back end no longer lets it read. It always shows the pairing screen,
// whatever session the display still holds. The pairing screen first asks for a new session from the
// display's own device cookie (so a screen that is still paired carries on) and, when that is refused,
// says "This screen was disconnected" and shows a new code. /screen/pair is not used here: it sends a
// display that holds a wall session to the board, and the two pages would send it back and forth.
// The page takes no input.
export default function WallReconnectPage() {
  return <PairingScreen />;
}
