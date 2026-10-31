import type { Metadata } from 'next';
import { SupportRequests } from '@/components/admin/SupportRequests';

// Support requests (TEN-076). At /admin/...: the proxy keeps it to the tenant administrator, and every call the
// page makes is to its own BFF routes, which check the role again.

export const metadata: Metadata = {
  title: 'Support requests',
  robots: { index: false },
};

export default function Page() {
  return <SupportRequests />;
}
