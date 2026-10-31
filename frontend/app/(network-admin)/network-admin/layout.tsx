import type { ReactNode } from 'react';
import { AdminFooter } from '@/components/admin/AdminFooter';
import { NetworkAdminNav } from '@/components/networkAdmin/NetworkAdminNav';
import { TenantHeader } from '@/components/tenant/TenantHeader';
import { currentProfile } from '@/lib/tenant/profile';

// The network administrator's pages (TEN-080): the organisation's own name at the top (the network owner is
// an organisation like any other, and a person who works for more than one always sees which), the
// navigation and the way to sign out. The role guard is the proxy's (`/network-admin` is for the role
// `network-admin` only); each page's calls are checked again by the BFF, and the network is the registry's
// answer for this organisation, never anything the browser holds.

export default async function NetworkAdminLayout({ children }: { children: ReactNode }) {
  const profile = await currentProfile();
  return (
    <>
      <TenantHeader profile={profile} />
      <NetworkAdminNav />
      {children}
      <AdminFooter />
    </>
  );
}
