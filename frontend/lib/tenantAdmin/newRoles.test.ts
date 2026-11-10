import { describe, expect, it } from 'vitest';
import { STAFF_ROLES } from '@/lib/auth/exchange';
import { GROUP_ROLE_CHOICES } from '@/lib/operator/bodies';
import { GROUP_ROLES as OPERATOR_GROUP_ROLES } from '@/lib/operator/views';
import { MAPPABLE_ROLES } from './bodies';
import { MAPPABLE_ROLE_WORDS } from './roles';
import { GROUP_ROLES } from './views';

// The Analytics User and Advisor v2 (DEC-1362) are listed wherever a tenant administrator maps a group to a role.
describe('the role lists of the tenant administration', () => {
  it.each(['analytics-user', 'advisor-v2'])('lists %s everywhere a role is mapped', (role) => {
    expect(MAPPABLE_ROLES).toContain(role);
    expect(GROUP_ROLE_CHOICES).toContain(role);
    expect(GROUP_ROLES).toContain(role);
    expect(OPERATOR_GROUP_ROLES).toContain(role);
    expect(MAPPABLE_ROLE_WORDS.map(([code]) => code)).toContain(role);
    expect(STAFF_ROLES).toContain(role);
  });

  it('says them in words', () => {
    expect(MAPPABLE_ROLE_WORDS).toContainEqual(['analytics-user', 'Analytics User']);
    expect(MAPPABLE_ROLE_WORDS).toContainEqual(['advisor-v2', 'Advisor v2']);
  });
});
