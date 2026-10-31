import type { Metadata } from 'next';
import { NetworkListings } from '@/components/networkAdmin/NetworkListings';

// The listings of the network: the owner admits, declines, pauses and reinstates (TEN-080).

export const metadata: Metadata = {
  title: 'Listings',
  robots: { index: false },
};

export default function Page() {
  return <NetworkListings />;
}
