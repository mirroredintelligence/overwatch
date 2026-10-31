import type { ReactNode } from 'react';
import { getSession } from '@/lib/auth/session';
import { currentProfile } from '@/lib/tenant/profile';
import { AppShell } from '@/components/shell/AppShell';

// The shell the route-group layouts use. It reads who is signed in (the sealed session, on this host) and
// the host's organisation name, and hands both to the frame. It decides nothing about access: the proxy
// guard and each page do that, so a person with no session sees the logo and Help only and the page
// redirects or says what it is for. A session or a profile that cannot be read is the same as none.

export async function StaffShell({ children }: { children: ReactNode }) {
  const [session, profile] = await Promise.all([getSession().catch(() => null), currentProfile()]);
  return (
    <AppShell role={session?.role ?? null} organisation={profile?.displayName ?? null}>
      {children}
    </AppShell>
  );
}
