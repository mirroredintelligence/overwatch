import { describe, expect, it } from 'vitest';
import { ROLES } from '@/lib/auth/session';
import { canAccess, rolesFor } from './access';

// TEN-068: the network pages are for the roles that see a network. The wall, the reporter, the
// anonymous link, support, audit and the two administrators have no network page.

describe('the network pages', () => {
  const SEES = ['advisor', 'clinical', 'lead', 'owner', 'exec'];

  it('are guarded for the five roles that see a network', () => {
    expect([...(rolesFor('/network/board') ?? [])].sort()).toEqual([...SEES].sort());
  });

  it.each(['/network/board', '/network/services', '/network/services/lst-0001', '/network/history', '/network/week', '/network/system-now', '/network/phones'])(
    '%s opens for those roles only',
    (path) => {
      for (const role of ROLES) expect(canAccess(role, path), `${role} ${path}`).toBe(SEES.includes(role));
    },
  );

  it('are not for the administrators: the network administrator has its own pages (TEN-080)', () => {
    for (const role of ['tenant-admin', 'network-admin'] as const) {
      expect(canAccess(role, '/network/board'), role).toBe(false);
    }
  });

  it('keeps /network-admin apart from /network: the first segment decides, so each has its own guard', () => {
    expect(rolesFor('/network-admin')).toEqual(['network-admin']);
    expect(rolesFor('/network')).not.toContain('network-admin');
    for (const path of ['/network-admin', '/network-admin/grants', '/Network-Admin/listings', '/x/../network-admin']) {
      for (const role of ROLES) expect(canAccess(role, path), `${role} ${path}`).toBe(role === 'network-admin');
    }
  });
});
