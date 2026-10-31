import { describe, expect, it } from 'vitest';
import { ROLES } from '@/lib/auth/session';
import { canAccess } from '@/lib/auth/access';
import { NETWORK_PAGES, ownHrefFor } from './links';

// TEN-069/070: the two routes of the scope switch. A network page is the network variant of one of the
// viewer's own pages, and the link back is to that page, or to the role's home when it has none.

describe('ownHrefFor', () => {
  it('is the advisor’s own board for an advisor, and the role’s home for the others', () => {
    expect(ownHrefFor('board', 'advisor')).toBe('/advisor/board');
    expect(ownHrefFor('board', 'lead')).toBe('/lead');
    expect(ownHrefFor('board', 'exec')).toBe('/planning');
    expect(ownHrefFor('board', 'owner')).toBe('/owner/criteria');
    expect(ownHrefFor('board', 'clinical')).toBe('/clinical');
  });

  it('is the lead’s own System now and phones pages for a lead', () => {
    expect(ownHrefFor('system-now', 'lead')).toBe('/lead');
    expect(ownHrefFor('phones', 'lead')).toBe('/lead/phones');
  });

  it('is the executive’s own week for an executive, and the lead’s page for a lead', () => {
    expect(ownHrefFor('week', 'exec')).toBe('/planning/week');
    expect(ownHrefFor('week', 'lead')).toBe('/lead');
  });

  it('is always a page the role may open', () => {
    for (const page of NETWORK_PAGES) {
      for (const role of ['advisor', 'clinical', 'lead', 'owner', 'exec'] as const) {
        expect(canAccess(role, ownHrefFor(page, role)), `${page} ${role}`).toBe(true);
      }
    }
  });

  it('has no role outside the five that see a network', () => {
    for (const role of ROLES.filter((r) => !['advisor', 'clinical', 'lead', 'owner', 'exec'].includes(r))) {
      expect(canAccess(role, '/network/board')).toBe(false);
    }
  });
});
