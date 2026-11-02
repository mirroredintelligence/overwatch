import type { ReactNode } from 'react';
import { Logo } from '@/components/brand/Logo';
import { SignOutButton, type SignOutFn } from '@/components/session/SignOutButton';
import { HelpLink } from '@/components/ui/HelpLink';
import type { Role } from '@/lib/auth/session';
import { homeFor, navFor, roleLabel } from '@/lib/shell/nav';
import { staffRoleWord } from '@/lib/shell/roleWords';
import { RoleSwitcher } from './RoleSwitcher';
import { ShellNav } from './ShellNav';
import styles from './AppShell.module.css';

// The frame of every staff area (artboards Advisor, ShiftLead, ExecApp1, ClinicalAdvisor, CriteriaOwner,
// ReporterApp1): a white header with the product logo, the person's role and organisation, the role's
// navigation, Help and Sign out, then the page at one width and spacing. The page keeps its own <main>;
// the shell adds none, so a page has one main landmark.
//
// `role` is the signed-in role, or null where nobody is signed in (a registration, the reporter's PIN
// screen, a help page opened from a link): the header is then the logo and Help only, with no navigation
// and no sign-out, because there is nothing to sign out of.
//
// `roles` is every staff role the person's groups give (DEC-1324). With more than one, the role is a chip that
// opens a menu to sign in again as another; with one, or none known, it is the plain words as before.

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
  const words = switchable ? Object.fromEntries(roles.map((r) => [r, roleLabel(r) ?? staffRoleWord(r)])) : undefined;
  const home = homeFor(role);
  return (
    <div className={styles.shell} data-el="APP-SHELL">
      <header className={styles.header} data-el="APP-HEADER">
        <div className={styles.bar}>
          <a className={styles.brand} href={home} aria-label="Overwatch home">
            <Logo height={32} />
          </a>
          {label !== null || organisation || switchable ? (
            <div className={styles.who} data-el="APP-WHO">
              {switchable ? <RoleSwitcher current={role} roles={roles} words={words} align="start" /> : label !== null ? <strong className={styles.role}>{label}</strong> : null}
              {organisation ? <span className={styles.org}>{organisation}</span> : null}
            </div>
          ) : null}
          {role !== null ? <ShellNav items={navFor(role)} home={home} /> : null}
          <div className={styles.actions}>
            <HelpLink />
            {role !== null ? <SignOutButton signOut={signOut} /> : null}
          </div>
        </div>
      </header>
      <div className={styles.page}>{children}</div>
    </div>
  );
}
