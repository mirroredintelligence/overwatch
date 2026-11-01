import { describe, expect, it } from 'vitest';
import { RAW_GROUPS } from '@/test/fixtures/tenantAdmin';
import { memberBody } from './bodies';
import { parseGroups, parseMemberChange } from './views';

describe('the member body (DEC-1317)', () => {
  it('passes one plain work address, trimmed, and nothing about the group', () => {
    expect(memberBody({ email: ' sam@example-trust.test ' })).toEqual({ email: 'sam@example-trust.test' });
  });

  it.each(['', 'x', 'a b@c.org', 'a..b@c.org', 'Sam <s@c.org>'])('refuses %j', (email) => {
    expect(() => memberBody({ email })).toThrow();
  });

  it('refuses a group name, a group id, a tenant, or another field', () => {
    for (const extra of [{ group: 'x' }, { groupName: 'Domain Admins' }, { groupId: 'x' }, { tenantId: 'other' }]) {
      expect(() => memberBody({ email: 'a@b.org', ...extra })).toThrow();
    }
    expect(() => memberBody(null)).toThrow();
  });
});

describe('what the page is told of the groups', () => {
  it('keeps the groups, their directory names and who is in them', () => {
    expect(parseGroups(RAW_GROUPS)).toEqual(RAW_GROUPS);
  });

  it('drops any field a screen does not show', () => {
    const noisy = { ...RAW_GROUPS, tenantId: 'x', groups: RAW_GROUPS.groups.map((g) => ({ ...g, internal: 1, members: g.members.map((m) => ({ ...m, userRefHash: 'h' })) })) };
    expect(JSON.stringify(parseGroups(noisy))).not.toMatch(/internal|userRefHash|tenantId/);
  });

  it('refuses a shape that is not the one expected', () => {
    expect(() => parseGroups({ setUp: 'yes', groups: [] })).toThrow();
    expect(() => parseGroups({ setUp: true, groups: [{ ...RAW_GROUPS.groups[0], role: 'god' }] })).toThrow();
    expect(() => parseMemberChange({ groupId: 'g', changed: 1 })).toThrow();
  });
});
