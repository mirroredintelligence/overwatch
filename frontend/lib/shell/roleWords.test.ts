import { describe, expect, it } from 'vitest';
import { staffRoleWord } from './roleWords';

describe('the role chip words (DEC-1362)', () => {
  it('names the Analytics User and Advisor v2', () => {
    expect(staffRoleWord('analytics-user')).toBe('Analytics User');
    expect(staffRoleWord('advisor-v2')).toBe('Advisor v2');
  });
});
