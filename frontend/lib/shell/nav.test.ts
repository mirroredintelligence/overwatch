import { describe, expect, it } from 'vitest';
import { canAccess } from '@/lib/auth/access';
import { ROLES } from '@/lib/auth/session';
import { homeFor, isCurrent, navFor, roleLabel } from './nav';

describe('staff navigation', () => {
  it('names the staff roles in words and no other', () => {
    expect(roleLabel('lead')).toBe('Shift lead');
    expect(roleLabel('clinical')).toBe('Clinical advisor');
    expect(roleLabel('owner')).toBe('Criteria owner');
    expect(roleLabel('exec')).toBe('Planning');
    expect(roleLabel('advisor')).toBe('Advisor');
    expect(roleLabel('reporter')).toBe('Service reporter');
    expect(roleLabel('wall')).toBeNull();
    expect(roleLabel('support')).toBeNull();
  });

  it('has an empty list for a role with no staff area', () => {
    expect(navFor('wall')).toEqual([]);
    expect(navFor('tenant-admin')).toEqual([]);
    expect(navFor('owner')).toEqual([]);
  });

  it('lists only pages the role may open (the same table the proxy reads)', () => {
    for (const role of ROLES) {
      for (const item of navFor(role)) {
        // The reporter's pages are under /app, which has no role guard (the pages check the session).
        expect(canAccess(role, item.href), `${role} ${item.href}`).toBe(true);
      }
    }
  });

  it('names the Analytics User and Advisor v2 and gives each its home (DEC-1362)', () => {
    expect(roleLabel('analytics-user')).toBe('Analytics User');
    expect(roleLabel('advisor-v2')).toBe('Advisor v2');
    expect(navFor('analytics-user')).toEqual([{ label: 'Home', href: '/analytics' }]);
    expect(navFor('advisor-v2')).toEqual([{ label: 'Home', href: '/advisor/v2' }]);
    // The advisor's home is the v2 workspace (DEC-1386); the v1 pages are not in the navigation.
    expect(navFor('advisor')[0]).toEqual({ label: 'Home', href: '/advisor/v2' });
    expect(navFor('advisor').map((item) => item.href)).not.toContain('/advisor');
  });

  it('starts every role with its home', () => {
    for (const role of ['advisor', 'clinical', 'lead', 'exec', 'reporter', 'advisor-v2', 'analytics-user'] as const) {
      expect(navFor(role)[0]?.href).toBe(homeFor(role));
    }
  });

  it('lists the coverage page for the planning role, which may open it, under a name no other item has', () => {
    const items = navFor('exec');
    expect(items).toContainEqual({ label: 'Coverage by time', href: '/planning/coverage' });
    expect(canAccess('exec', '/planning/coverage')).toBe(true);
    for (const role of ROLES) {
      const labels = navFor(role).map((item) => item.label);
      expect(new Set(labels).size).toBe(labels.length);
    }
  });

  it('sends the logo to the role home, the reporter app, or the front page', () => {
    expect(homeFor('lead')).toBe('/lead');
    expect(homeFor('owner')).toBe('/criteria'); // the landing page, DEC-1310
    expect(homeFor('exec')).toBe('/planning');
    expect(homeFor('reporter')).toBe('/app');
    expect(homeFor(null)).toBe('/');
  });

  it('marks the home only on its own path, and the others on their pages and the pages below', () => {
    expect(isCurrent('/lead', '/lead', '/lead')).toBe(true);
    expect(isCurrent('/lead/phones', '/lead', '/lead')).toBe(false);
    expect(isCurrent('/lead/phones', '/lead/phones', '/lead')).toBe(true);
    expect(isCurrent('/lead/phones/move', '/lead/phones', '/lead')).toBe(true);
    expect(isCurrent('/lead/phones/', '/lead/phones', '/lead')).toBe(true);
    expect(isCurrent('/lead/phonesx', '/lead/phones', '/lead')).toBe(false);
  });
});
