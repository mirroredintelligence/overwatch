import type { ReactNode } from 'react';
import type { SignOutFn } from '@/components/session/SignOutButton';
import type { Role } from '@/lib/auth/session';
import { homeFor, navFor, roleLabel } from '@/lib/shell/nav';
import { staffRoleWord } from '@/lib/shell/roleWords';
import { AppFrame } from './AppFrame';
import type { FrameItem } from './frame';
import type { IconName } from './icons';
import styles from './AppShell.module.css';

// The frame of every staff area (artboards Advisor, ShiftLead, ExecApp1, ClinicalAdvisor, CriteriaOwner,
// ReporterApp1), drawn by AppFrame (DEC-1326): the dark rail with the role's pages, a top bar with the
// organisation, the current page's name, the role and Sign out, then the page at one width and spacing. The
// page keeps its own <main>; the shell adds none, so a page has one main landmark.
//
// `role` is the signed-in role, or null where nobody is signed in (a registration, the reporter's PIN
// screen, a help page opened from a link): the rail is then the mark and Help only, with no navigation
// and no sign-out, because there is nothing to sign out of.
//
// `roles` is every staff role the person's groups give (DEC-1324). With more than one, the role is a chip that
// opens a menu to sign in again as another; with one, or none known, it is the plain words as before.

// The icon of each page in the role navigation (lib/shell/nav.ts holds the pages; the pictures are the frame's).
const ICONS: Readonly<Record<string, IconName>> = {
  '/advisor': 'home',
  '/advisor/board': 'board',
  '/clinical': 'pulse',
  '/clinical/requests': 'inbox',
  '/lead': 'home',
  '/lead/phones': 'phone',
  '/lead/reporters': 'checklist',
  '/lead/registrations': 'userPlus',
  '/lead/audit': 'history',
  '/planning': 'home',
  '/planning/services': 'list',
  '/planning/week': 'calendar',
  '/planning/alerts': 'bell',
  '/planning/coverage': 'chart',
  '/app': 'edit',
  '/app/settings': 'sliders',
};

function frameItems(role: Role, home: string): readonly FrameItem[] {
  return navFor(role).map((item) => ({ label: item.label, href: item.href, icon: ICONS[item.href] ?? 'list', exact: item.href === home }));
}

export function AppShell({
  role,
  roles,
  organisation,
  signOut,
  children,
}: {
  role: Role | null;
  /** The roles the person may switch between; the chip shows when there are two or more. */
  roles?: readonly Role[];
  /** The organisation's display name from its profile, or null when the host has none. */
  organisation?: string | null;
  signOut?: SignOutFn;
  children: ReactNode;
}) {
  const label = role === null ? null : roleLabel(role);
  const switchable = role !== null && roles !== undefined && roles.length > 1 && roles.includes(role);
  // The chip speaks the header's own words for a role where it has them, so the chip and the menu agree.
  const words = Object.fromEntries([...(switchable ? roles : []), ...(role === null ? [] : [role])].map((r) => [r, roleLabel(r) ?? staffRoleWord(r)]));
  const home = homeFor(role);
  return (
    <AppFrame
      portal="staff"
      items={role === null ? [] : frameItems(role, home)}
      homeHref={home}
      organisation={organisation}
      role={label !== null || switchable ? (role ?? undefined) : undefined}
      roles={switchable ? roles : undefined}
      roleWords={words}
      signOut={signOut}
      showSignOut={role !== null}
    >
      <div className={styles.page}>{children}</div>
    </AppFrame>
  );
}
