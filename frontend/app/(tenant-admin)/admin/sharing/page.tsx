import type { Metadata } from 'next';
import { SharingOverview } from '@/components/sharing/SharingOverview';

// Sharing with the network (TEN-081). At /admin/sharing: the proxy keeps it to the tenant administrator, and
// every call the page makes is to its own BFF routes (/api/bff/sharing), which check the role again.

export const metadata: Metadata = {
  title: 'Sharing with the network',
  robots: { index: false },
};

export default function Page() {
  return <SharingOverview />;
}
