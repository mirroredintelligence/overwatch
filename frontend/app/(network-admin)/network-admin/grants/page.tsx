import type { Metadata } from 'next';
import { NetworkGrants } from '@/components/networkAdmin/NetworkGrants';

// The grants of the network: the owner approves or declines (TEN-080).

export const metadata: Metadata = {
  title: 'Grants',
  robots: { index: false },
};

export default function Page() {
  return <NetworkGrants />;
}
