import type { Metadata } from 'next';
import { AccessLog } from '@/components/admin/AccessLog';

// Who has accessed your organisation (TEN-076). At /admin/...: the proxy keeps it to the tenant administrator, and every call the
// page makes is to its own BFF routes, which check the role again.

export const metadata: Metadata = {
  title: 'Who has accessed your organisation',
  robots: { index: false },
};

export default function Page() {
  return <AccessLog />;
}
