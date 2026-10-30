import { describe, expect, it } from 'vitest';
import { share } from './share';

describe('share', () => {
  it('computes 18 of 112 as 16%', () => {
    expect(share(18, 112)).toBe(16);
  });

  it('returns null for a suppressed row, whose count is not shown', () => {
    expect(share(null, 112)).toBeNull();
  });

  it('returns null when the whole is zero, so no share is invented', () => {
    expect(share(3, 0)).toBeNull();
  });
});
