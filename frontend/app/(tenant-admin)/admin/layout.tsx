import type { ReactNode } from 'react';
import { AdminShell } from '@/components/admin/AdminShell';
import { getSession } from '@/lib/auth/session';
import { currentProfile } from '@/lib/tenant/profile';

// The tenant administrator's pages (TEN-076): the shared admin frame, with the organisation's own name at the
// top (so a person who works for more than one always sees which), the navigation and the way to sign out.
// The role guard is the proxy's; each page's calls are checked again by the BFF. The role chip lists the
// roles the person's groups give (DEC-1324); a session from before that lists only the role it is in.

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const [profile, session] = await Promise.all([currentProfile(), getSession().catch(() => null)]);
  return (
    <AdminShell
      portal="tenant"
      organisation={profile?.displayName ?? null}
      staffRole={session?.role}
      staffRoles={session ? (session.roles ?? [session.role]) : []}
    >
      {children}
    </AdminShell>
  );
}
