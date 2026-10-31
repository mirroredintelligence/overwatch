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

  it('does not guard /network-admin by this prefix (its own task)', () => {
    expect(rolesFor('/network-admin')).toBeNull();
  });
});
