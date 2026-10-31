import type { ReactNode } from 'react';
import { AdminNav } from '@/components/admin/AdminNav';
import { AdminFooter } from '@/components/admin/AdminFooter';
import { TenantHeader } from '@/components/tenant/TenantHeader';
import { currentProfile } from '@/lib/tenant/profile';

// The tenant administrator's pages (TEN-076): the organisation's own name at the top (so a person who works
// for more than one always sees which), the navigation and the way to sign out. The role guard is the
// proxy's; each page's calls are checked again by the BFF.

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const profile = await currentProfile();
  return (
    <>
      <TenantHeader profile={profile} />
      <AdminNav />
      {children}
      <AdminFooter />
    </>
  );
}
