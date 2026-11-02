import type { ReactNode } from 'react';
import { AdminShell } from '@/components/admin/AdminShell';
import { getSession } from '@/lib/auth/session';
import { currentProfile } from '@/lib/tenant/profile';

// The network administrator's pages (TEN-080): the shared admin frame, with the organisation's own name at the
// top (the network owner is an organisation like any other, and a person who works for more than one always
// sees which), the navigation and the way to sign out. The role guard is the proxy's (`/network-admin` is for
// the role `network-admin` only); each page's calls are checked again by the BFF, and the network is the
// registry's answer for this organisation, never anything the browser holds. The role chip lists the roles the
// person's groups give (DEC-1324); a session from before that lists only the role it is in.

export default async function NetworkAdminLayout({ children }: { children: ReactNode }) {
  const [profile, session] = await Promise.all([currentProfile(), getSession().catch(() => null)]);
  return (
    <AdminShell
      portal="network"
      organisation={profile?.displayName ?? null}
      staffRole={session?.role}
      staffRoles={session ? (session.roles ?? [session.role]) : []}
    >
      {children}
    </AdminShell>
  );
}
