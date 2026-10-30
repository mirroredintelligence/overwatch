import type { Metadata } from 'next';
import { BookingDecision } from '@/components/reporter/BookingDecision';

// The service's booking request page, opened from a booking text or email (L02, W19). It holds a
// bearer token in its address, so it is never cached or indexed, asks the browser not to send its
// address as a referrer, and loads nothing from any other origin. A malformed token is answered by
// the BFF as a closed link, with no request to the back end for it.

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'DIUCS booking request',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

export default async function BookingPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <BookingDecision token={token} />;
}
