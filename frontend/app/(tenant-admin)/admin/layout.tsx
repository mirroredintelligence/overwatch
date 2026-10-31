import type { ReactNode } from 'react';
import { AdminShell } from '@/components/admin/AdminShell';
import { currentProfile } from '@/lib/tenant/profile';

// The tenant administrator's pages (TEN-076): the shared admin frame, with the organisation's own name at the
// top (so a person who works for more than one always sees which), the navigation and the way to sign out.
// The role guard is the proxy's; each page's calls are checked again by the BFF.

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const profile = await currentProfile();
  return (
    <AdminShell portal="tenant" organisation={profile?.displayName ?? null}>
      {children}
    </AdminShell>
  );
}
