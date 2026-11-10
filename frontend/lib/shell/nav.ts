import { roleHome } from '@/lib/auth/access';
import type { Role } from '@/lib/auth/session';

// What the staff header shows for a signed-in role: the role in words, the home the logo links to and the
// pages the role can use. Every href is a page the proxy guard (lib/auth/access.ts) lets that role open, so
// nothing here points at a page the person would be turned away from. Network pages are not listed: each
// page that has a network view already links to it, and a second link of the same name would be a
// duplicate (for the same reason the shift lead's "Wall screens" link, which the overview carries, is not
// repeated here). The criteria owner has one page per service and the landing at /criteria (DEC-1310), so has the home only.

export type NavItem = { readonly label: string; readonly href: string };

const ROLE_LABELS: Readonly<Partial<Record<Role, string>>> = {
  advisor: 'Advisor',
  clinical: 'Clinical advisor',
  lead: 'Shift lead',
  owner: 'Criteria owner',
  exec: 'Planning',
  reporter: 'Service reporter',
};

const NAV: Readonly<Partial<Record<Role, readonly NavItem[]>>> = {
  advisor: [
    { label: 'Home', href: '/advisor' },
    { label: 'Wall board', href: '/advisor/board' },
  ],
  clinical: [
    { label: 'On duty', href: '/clinical' },
    { label: 'Requests', href: '/clinical/requests' },
  ],
  lead: [
    { label: 'Overview', href: '/lead' },
    { label: 'Phones and services', href: '/lead/phones' },
    { label: 'Set-up progress', href: '/lead/reporters' },
    { label: 'Registrations', href: '/lead/registrations' },
    { label: 'Missed replies', href: '/lead/replies' },
    { label: 'Audit replay', href: '/lead/audit' },
  ],
  exec: [
    { label: 'Home', href: '/planning' },
    { label: 'All services', href: '/planning/services' },
    { label: 'This week', href: '/planning/week' },
    { label: 'Alerts', href: '/planning/alerts' },
    { label: 'Coverage by time', href: '/planning/coverage' },
  ],
  reporter: [
    { label: 'Update', href: '/app' },
    { label: 'Settings', href: '/app/settings' },
  ],
};

/** The role in words for the header, or null for a role the staff header does not name. */
export function roleLabel(role: Role): string | null {
  return ROLE_LABELS[role] ?? null;
}

/** The pages in the header's navigation for a role. Empty for a role with no staff area. */
export function navFor(role: Role): readonly NavItem[] {
  return NAV[role] ?? [];
}

/** Where the logo goes: the role's home, the reporter's app, or the front page when nobody is signed in. */
export function homeFor(role: Role | null): string {
  if (role === null) return '/';
  return role === 'reporter' ? '/app' : roleHome(role);
}

/**
 * Whether a nav item is the current page. The first item of a role is its home and matches only its own
 * path, so "Overview" is not marked on every page below /lead; the others match their own path and the
 * pages below it.
 */
export function isCurrent(pathname: string, href: string, home: string): boolean {
  const path = pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
  if (href === home) return path === href;
  return path === href || path.startsWith(`${href}/`);
}
