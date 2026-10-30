import type { Metadata } from 'next';
import { AdminOverview } from '@/components/admin/AdminOverview';

// Administration (TEN-076). At /admin/...: the proxy keeps it to the tenant administrator, and every call the
// page makes is to its own BFF routes, which check the role again.

export const metadata: Metadata = {
  title: 'Administration',
  robots: { index: false },
};

export default function Page() {
  return <AdminOverview />;
}
