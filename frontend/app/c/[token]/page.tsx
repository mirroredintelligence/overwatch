import type { Metadata } from 'next';
import { CheckInPage } from '@/components/checkin/CheckInPage';
import { LinkExpired } from '@/components/reporter/LinkExpired';

// The check-in page a service's printed QR code opens (DEC-1346). The code is a bearer token in the address, so, as for
// the capacity link page: the page reads it only through its own BFF; it loads nothing from any other origin; it asks
// the browser not to send its address as a referrer; and it is never cached or indexed. A code that is unknown,
// replaced or of another kind shows the same message.

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Overwatch check-in',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

export default async function CheckInRoute({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!TOKEN_SHAPE.test(token)) return <LinkExpired token={token} csrfToken={null} />;
  return <CheckInPage token={token} />;
}
