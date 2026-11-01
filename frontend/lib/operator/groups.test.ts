import { describe, expect, it } from 'vitest';
import { entraGroupsBody, groupMemberBody } from './bodies';
import { parseGroupsMade, parseMemberAdded } from './views';

describe('the groups body (DEC-1317)', () => {
  it('passes the roles asked for, once each', () => {
    expect(entraGroupsBody({ roles: ['lead', 'clinical', 'lead'] })).toEqual({ roles: ['lead', 'clinical'] });
    expect(entraGroupsBody({})).toEqual({ roles: [] });
  });

  it.each([['tenant-admin'], ['network-admin'], ['platform-operator'], ['support'], ['reporter'], ['Lead'], [7]])('refuses the role %j (the administrators’ group is always made, and the others have no group)', (role) => {
    expect(() => entraGroupsBody({ roles: [role] })).toThrow();
  });

  it('refuses anything that is a name or an id of a group, a tenant, or any other field', () => {
    for (const body of [{ roles: [], names: ['Domain Admins'] }, { roles: [], groupId: 'x' }, { roles: [], tenantId: 'other-org' }, { roles: 'lead' }, null, []]) {
      expect(() => entraGroupsBody(body)).toThrow();
    }
    expect(() => entraGroupsBody({ roles: Array.from({ length: 13 }, () => 'lead') })).toThrow();
  });
});

describe('the first member body (DEC-1317)', () => {
  it('passes the group by role and one plain work address, trimmed', () => {
    expect(groupMemberBody({ role: 'tenant-admin', email: ' jane@example-trust.test ' })).toEqual({ role: 'tenant-admin', email: 'jane@example-trust.test' });
    expect(groupMemberBody({ role: 'lead', email: 'a@b.org' })).toEqual({ role: 'lead', email: 'a@b.org' });
  });

  it.each(['', 'no-at', 'a@', 'a b@c.org', 'a..b@c.org', 'Jane <j@c.org>'])('refuses the address %j', (email) => {
    expect(() => groupMemberBody({ role: 'lead', email })).toThrow();
  });

  it('refuses a role with no group, a group id, a tenant, and anything else', () => {
    expect(() => groupMemberBody({ role: 'platform-operator', email: 'a@b.org' })).toThrow();
    expect(() => groupMemberBody({ role: 'lead', email: 'a@b.org', groupId: 'dddddddd-0000-4000-8000-000000000001' })).toThrow();
    expect(() => groupMemberBody({ role: 'lead', email: 'a@b.org', tenantId: 'other-org' })).toThrow();
    expect(() => groupMemberBody({ email: 'a@b.org' })).toThrow();
  });
});

describe('what the page is told', () => {
  it('keeps what a screen shows of the groups made and drops the rest', () => {
    const view = parseGroupsMade({ groups: [{ role: 'lead', name: 'RXX01_overwatch_lead', groupId: 'g-1', created: false, assigned: true, internal: 'x' }], recorded: true, other: 1 });
    expect(view).toEqual({ groups: [{ role: 'lead', name: 'RXX01_overwatch_lead', groupId: 'g-1', created: false, assigned: true }], recorded: true });
  });

  it('refuses a shape that is not the one expected, and a role that is not one', () => {
    expect(() => parseGroupsMade({ groups: [{ role: 'god', name: 'x', groupId: 'g', created: true, assigned: true }], recorded: true })).toThrow();
    expect(() => parseGroupsMade({ groups: 'x', recorded: true })).toThrow();
    expect(() => parseMemberAdded({ groupId: 'g', added: 'yes', recorded: true })).toThrow();
  });

  it('tells a member was added and keeps no address or id of a person', () => {
    expect(parseMemberAdded({ groupId: 'g-1', added: true, recorded: true, userRefHash: 'h', email: 'a@b.org' })).toEqual({ groupId: 'g-1', added: true, recorded: true });
  });
});
