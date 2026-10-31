import type { Metadata } from 'next';
import { NetworkAdminHistory } from '@/components/networkAdmin/NetworkAdminHistory';

// The read-only history of the network's membership and grant decisions (TEN-080).

export const metadata: Metadata = {
  title: 'History',
  robots: { index: false },
};

export default function Page() {
  return <NetworkAdminHistory />;
}
