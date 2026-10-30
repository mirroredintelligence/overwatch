import { describe, expect, it } from 'vitest';
import { isGuid, isTenantId } from './ids';

describe('isTenantId', () => {
  it.each(['trust-a', 'ab', 'a1', 'x'.repeat(31), 'tenant-12'])('accepts %s', (value) => {
    expect(isTenantId(value)).toBe(true);
  });

  it.each(['', 'a', 'x'.repeat(32), 'Trust-A', '-a', 'a b', 'a/b', 'a.b', 'net-capacity', 'net-', 'a\n', 'platform id'])(
    'refuses %j',
    (value) => {
      expect(isTenantId(value)).toBe(false);
    },
  );

  it('refuses what is not text', () => {
    for (const value of [null, undefined, 7, {}, ['trust-a']]) {
      expect(isTenantId(value as unknown as string)).toBe(false);
    }
  });
});

describe('isGuid', () => {
  it('accepts a GUID in either case and refuses everything else', () => {
    expect(isGuid('11111111-1111-4111-8111-111111111111')).toBe(true);
    expect(isGuid('AAAAAAAA-0000-4000-8000-000000000001')).toBe(true);
    for (const value of ['', 'not-a-guid', '11111111111141118111111111111111', '11111111-1111-4111-8111-11111111111g']) {
      expect(isGuid(value)).toBe(false);
    }
  });
});
