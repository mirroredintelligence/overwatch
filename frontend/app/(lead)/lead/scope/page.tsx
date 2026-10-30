import type { Metadata } from 'next';
import { ScopeList } from '@/components/lead/ScopeList';

export const metadata: Metadata = {
  title: 'Services in scope · DIUCS capacity',
};

// Read at every request: the scope list is never cached. The page takes no input; the organisation
// is the session's, never the address's (DEC-130).
export const dynamic = 'force-dynamic';

export default function ScopePage() {
  return <ScopeList />;
}
