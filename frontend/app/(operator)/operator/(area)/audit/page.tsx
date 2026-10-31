import type { Metadata } from 'next';
import { AuditChain } from '@/components/operator/AuditChain';

export const metadata: Metadata = { title: 'Audit chain - platform console', robots: { index: false } };

// The platform audit chain (TEN-083), at /operator/audit: the operator's.
export default function Page() {
  return <AuditChain />;
}
