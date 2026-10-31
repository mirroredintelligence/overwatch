import type { Metadata } from 'next';
import { NetworkMembers } from '@/components/networkAdmin/NetworkMembers';

// Network members and the agreement (TEN-080). At /network-admin: the proxy keeps it to the network
// administrator, and every call the page makes is to its own BFF routes, which check the role again.

export const metadata: Metadata = {
  title: 'Network members',
  robots: { index: false },
};

export default function Page() {
  return <NetworkMembers />;
}
