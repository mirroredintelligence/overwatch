import type { Metadata } from 'next';
import { AuditSearch } from '@/components/lead/AuditSearch';

// The audit search (W47). At /lead/audit.

export const metadata: Metadata = {
  title: 'Audit replay - DIUCS capacity',
  robots: { index: false },
};

export default function AuditPage() {
  return <AuditSearch />;
}
