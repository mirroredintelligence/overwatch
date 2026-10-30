import { describe, expect, it } from 'vitest';
import { rolesFor } from '@/lib/auth/access';
import { CASE_ROLES } from './roles';

describe('who may work a call (DEC-860)', () => {
  it('is the advisor only, and the page guard for /advisor says the same', () => {
    expect([...CASE_ROLES]).toEqual(['advisor']);
    expect([...(rolesFor('/advisor/case/case-1') ?? [])]).toEqual([...CASE_ROLES]);
  });

  it('does not admit a shift lead, whom the back end refuses on a case (DEC-397, DEC-632)', () => {
    expect(CASE_ROLES).not.toContain('lead');
  });
});
