import type { ReactNode } from 'react';
import { WorkspaceProvider } from '@/components/workspace/WorkspaceProvider';
import { getSession } from '@/lib/auth/session';
import { currentProfile } from '@/lib/tenant/profile';

// The shell the advisor v2 route group uses (DEC-1376, WS-SHL). It makes the same two reads as StaffShell (the sealed
// session and the host's organisation name) but draws no rail: it hands both to the workspace provider, which the
// pages read through useWorkspace(). A session or a profile that cannot be read is the same as none. It decides
// nothing about access; the proxy guard and each page do that. It lives in app/, beside StaffShell, because a
// component may run in the browser and so may not read the session or the profile (eslint no-restricted-imports).

export async function WorkspaceShell({ children }: { children: ReactNode }) {
  const [session, profile] = await Promise.all([getSession().catch(() => null), currentProfile().catch(() => null)]);
  const role = session?.role ?? null;
  const roles = session ? (session.roles ?? [session.role]) : [];
  return (
    <WorkspaceProvider role={role} roles={roles} organisation={profile?.displayName ?? null}>
      {children}
    </WorkspaceProvider>
  );
}
