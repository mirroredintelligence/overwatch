'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { Logo } from '@/components/brand/Logo';
import { SignOutButton, type SignOutFn } from '@/components/session/SignOutButton';
import { signOutOperator } from '@/lib/operator/browser';
import type { OperatorRole } from '@/lib/operator/session';
import { roleWord } from '@/lib/tenantAdmin/words';
import { RoleSwitcher, staffRoleWord } from '@/components/shell/RoleSwitcher';
import { ADMIN_PAGES } from './AdminOverview';
import styles from './AdminShell.module.css';

// One frame for the three administration portals (design canvas "Overwatch admin portals"): the platform
// console, the tenant administration and the network administration. At the top, the logo, which portal and
// (for a tenant or a network) which organisation, who is signed in and the way to sign out; under it the
// portal's navigation, with the current page marked in the markup and by an underline (never colour alone).
// The page's own `<main>` follows. The role guard is the proxy's; this only draws what the portal has.

export type Portal = 'operator' | 'tenant' | 'network';
type Item = readonly [string, string];

const TENANT_ITEMS: readonly Item[] = [['Overview', '/admin'], ...ADMIN_PAGES];
const NETWORK_ITEMS: readonly Item[] = [
  ['Members', '/network-admin'],
  ['Grants', '/network-admin/grants'],
  ['Listings', '/network-admin/listings'],
  ['History', '/network-admin/history'],
];
const OPERATOR_ITEMS: Record<OperatorRole, readonly Item[]> = {
  'platform-operator': [
    ['Tenants', '/operator'],
    ['Audit chain', '/operator/audit'],
  ],
  support: [
    ['Support requests', '/operator/support'],
    ['Tenants', '/operator'],
  ],
};

const HOME: Record<Portal, string> = { operator: '/operator', tenant: '/admin', network: '/network-admin' };
const NAV_LABEL: Record<Portal, string> = { operator: 'Platform console', tenant: 'Administration', network: 'Network administration' };
const SIGNED_IN_AS: Record<Portal, string> = { operator: '', tenant: 'tenant administrator', network: 'network administrator' };

export function navItems(portal: Portal, role?: OperatorRole): readonly Item[] {
  if (portal === 'operator') return OPERATOR_ITEMS[role ?? 'support'];
  return portal === 'tenant' ? TENANT_ITEMS : NETWORK_ITEMS;
}

/** True when `href` is the page the person is on (or one of its own sub-pages). The home page matches itself only. */
export function isCurrent(portal: Portal, pathname: string, href: string): boolean {
  const home = HOME[portal];
  if (href === home) {
    const bare = pathname.replace(/\/$/, '');
    return bare === home || (portal === 'operator' && bare.startsWith('/operator/tenants'));
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export type AdminShellProps = {
  portal: Portal;
  /** The operator's role: said in the header and decides the console's navigation. */
  role?: OperatorRole;
  /** The organisation's display name (tenant and network portals); nothing else about it is shown. */
  organisation?: string | null;
  /** The staff role the session is signed in as, and every role the person may switch to (DEC-1324). */
  staffRole?: string;
  staffRoles?: readonly string[];
  signOut?: SignOutFn;
  children: ReactNode;
};

export function AdminShell({ portal, role, organisation, staffRole, staffRoles, signOut, children }: AdminShellProps) {
  const pathname = usePathname() ?? '';
  const context = portal === 'operator' ? 'Platform console' : (organisation ?? NAV_LABEL[portal]);
  const who = portal === 'operator' ? roleWord(role ?? 'support').toLowerCase() : SIGNED_IN_AS[portal];
  const switchable = portal !== 'operator' && staffRole !== undefined && (staffRoles?.length ?? 0) > 1;
  return (
    <div className={styles.shell} data-portal={portal}>
      <header className={styles.header}>
        <a className={styles.logo} href={HOME[portal]}>
          <Logo height={32} />
        </a>
        <span className={styles.context} data-el={portal === 'operator' ? 'ADMIN-CONTEXT' : 'TENANT-HEADER'}>
          {context}
        </span>
        <div className={styles.who}>
          {switchable ? (
            <span data-el="ADMIN-SIGNED-IN-AS">
              Signed in as <RoleSwitcher current={staffRole} roles={staffRoles ?? []} />
            </span>
          ) : (
            <span data-el="ADMIN-SIGNED-IN-AS">{`Signed in as ${staffRole !== undefined && portal !== 'operator' ? staffRoleWord(staffRole).toLowerCase() : who}`}</span>
          )}
          <SignOutButton signOut={portal === 'operator' ? (signOut ?? signOutOperator) : signOut} />
        </div>
        <nav className={styles.nav} aria-label={NAV_LABEL[portal]}>
          {navItems(portal, role).map(([name, href]) => (
            <a key={href} className={styles.navLink} href={href} aria-current={isCurrent(portal, pathname, href) ? 'page' : undefined}>
              {name}
            </a>
          ))}
        </nav>
      </header>
      {children}
    </div>
  );
}
