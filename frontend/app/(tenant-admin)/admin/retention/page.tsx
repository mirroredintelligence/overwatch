import type { Metadata } from 'next';
import { RetentionForm } from '@/components/admin/RetentionForm';

// Data retention (TEN-076). At /admin/...: the proxy keeps it to the tenant administrator, and every call the
// page makes is to its own BFF routes, which check the role again.

export const metadata: Metadata = {
  title: 'Data retention',
  robots: { index: false },
};

export default function Page() {
  return <RetentionForm />;
}
