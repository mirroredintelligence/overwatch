import { roleHome } from '@/lib/auth/access';
import type { Role } from '@/lib/auth/session';

// The two routes of the scope switch (TEN-069, TEN-070): a network page is the network variant of one of the
// viewer's own pages. The link back is that page, or the role's home when the role has none. Fixed routes
// only: a change of scope is a navigation, never a parameter.

export const NETWORK_PAGES = ['board', 'services', 'history', 'system-now', 'phones', 'week'] as const;
export type NetworkPage = (typeof NETWORK_PAGES)[number];

/** The network page's route. */
export const NETWORK_ROUTES: Record<NetworkPage, string> = {
  board: '/network/board',
  services: '/network/services',
  history: '/network/history',
  'system-now': '/network/system-now',
  phones: '/network/phones',
  week: '/network/week',
};

/** The viewer's own page that a network page is the variant of. */
export function ownHrefFor(page: NetworkPage, role: Role): string {
  if (page === 'system-now' && role === 'lead') return '/lead';
  if (page === 'phones' && role === 'lead') return '/lead/phones';
  if (page === 'week' && role === 'exec') return '/planning/week';
  if (page === 'board' && role === 'advisor') return '/advisor/board';
  return roleHome(role);
}
