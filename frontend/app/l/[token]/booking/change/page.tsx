import type { Metadata } from 'next';
import { BookingChange } from '@/components/reporter/BookingChange';

// The service's change page for a confirmed booking (L02, W22), opened from the booked page. It holds
// a bearer token in its address, so it is never cached or indexed and sends no referrer.

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'DIUCS booking',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

export default async function BookingChangePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <BookingChange token={token} />;
}
