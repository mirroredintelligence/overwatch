'use client';

import type { ReactNode } from 'react';
import { type SignOutFn } from '@/components/session/SignOutButton';
import { AppFrame } from '@/components/shell/AppFrame';
import { itemIsCurrent, type FrameItem } from '@/components/shell/frame';
import type { IconName } from '@/components/shell/icons';
import { signOutOperator } from '@/lib/operator/browser';
import type { OperatorRole } from '@/lib/operator/session';
import { roleWord } from '@/lib/tenantAdmin/words';

// The frame of the three administration portals (design canvas "Overwatch admin portals"): the platform
// console, the tenant administration and the network administration, now drawn by AppFrame (DEC-1326): the
// dark rail with the portal's pages, and a top bar with the organisation (for a tenant or a network), the
// page's name, the role and the way to sign out. The current page is marked in the markup (aria-current) and
// by the pill. The page's own `<main>` follows. The role guard is the proxy's; this only draws what the portal has.

export type Portal = 'operator' | 'tenant' | 'network';
type Item = readonly [string, string];

const HOME: Record<Portal, string> = { operator: '/operator', tenant: '/admin', network: '/network-admin' };
const NAV_LABEL: Record<Portal, string> = { operator: 'Platform console', tenant: 'Administration', network: 'Network administration' };
const DEFAULT_ROLE: Record<Portal, string> = { operator: 'support', tenant: 'tenant-admin', network: 'network-admin' };

type Spec = readonly [label: string, href: string, icon: IconName];

const TENANT_ITEMS: readonly Spec[] = [
  ['Overview', '/admin', 'home'],
  ['People', '/admin/users', 'people'],
  ['Contacts', '/admin/contacts', 'mail'],
  ['Settings', '/admin/config', 'sliders'],
  ['Retention', '/admin/retention', 'db'],
  ['Email', '/admin/email', 'send'],
  ['Sharing', '/admin/sharing', 'share'],
  ['Access', '/admin/access', 'shield'],
  ['Support', '/admin/support', 'buoy'],
];
const NETWORK_ITEMS: readonly Spec[] = [
  ['Members', '/network-admin', 'people'],
  ['Grants', '/network-admin/grants', 'key'],
  ['Listings', '/network-admin/listings', 'list'],
  ['History', '/network-admin/history', 'history'],
];
const OPERATOR_ITEMS: Record<OperatorRole, readonly Spec[]> = {
  'platform-operator': [
    ['Organisations', '/operator', 'building'],
    ['Audit', '/operator/audit', 'list'],
  ],
  support: [
    ['Support', '/operator/support', 'buoy'],
    ['Organisations', '/operator', 'building'],
  ],
};

function specs(portal: Portal, role?: OperatorRole): readonly Spec[] {
  if (portal === 'operator') return OPERATOR_ITEMS[role ?? 'support'];
  return portal === 'tenant' ? TENANT_ITEMS : NETWORK_ITEMS;
}

/** The portal's own pages as [label, href], for the portal and the role. */
export function navItems(portal: Portal, role?: OperatorRole): readonly Item[] {
  return specs(portal, role).map(([label, href]) => [label, href] as const);
}

// A portal's home matches itself only, not the pages below it; the console's home also stands for its
// organisation pages (/operator/tenants/...), which have no item of their own.
function frameItem(portal: Portal, [label, href, icon]: Spec): FrameItem {
  const home = href === HOME[portal];
  return { label, href, icon, exact: home, alsoMatch: home && portal === 'operator' ? ['/operator/tenants'] : undefined };
}

/** True when `href` is the page the person is on (or one of its own sub-pages). The home page matches itself only. */
export function isCurrent(portal: Portal, pathname: string, href: string): boolean {
  return itemIsCurrent(pathname, frameItem(portal, ['', href, 'home']));
}

export type AdminShellProps = {
  portal: Portal;
  /** The operator's role: said in the top bar and decides the console's navigation. */
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
  const operator = portal === 'operator';
  const items = specs(portal, role).map((spec) => frameItem(portal, spec));
  const signedInRole = operator ? (role ?? DEFAULT_ROLE.operator) : (staffRole ?? DEFAULT_ROLE[portal]);
  return (
    <AppFrame
      portal={portal}
      items={items}
      navLabel={NAV_LABEL[portal]}
      homeHref={HOME[portal]}
      organisation={operator ? 'Platform console' : (organisation ?? NAV_LABEL[portal])}
      role={signedInRole}
      roles={operator ? undefined : staffRoles}
      roleWords={operator ? { [signedInRole]: roleWord(signedInRole) } : undefined}
      signOut={operator ? (signOut ?? signOutOperator) : signOut}
    >
      {children}
    </AppFrame>
  );
}
