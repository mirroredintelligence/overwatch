import { describe, expect, it } from 'vitest';
import { attentionClass, attentionOf } from './attention';

describe('attentionOf (DEC-1365)', () => {
  it.each([
    ['not-updated', false, 'stale'],
    ['last-known', false, 'stale'],
    ['accepting', true, 'stale'],
    ['over-capacity', true, 'stale'],
    ['limited', true, 'stale'],
    ['over-capacity', false, 'over'],
    ['limited', false, 'limited'],
    ['not-accepting', false, 'closed'],
    ['accepting', false, null],
    ['out-of-hours', false, null],
  ])('%s (stale: %s) is %s', (status, stale, expected) => {
    expect(attentionOf({ status, stale })).toBe(expected);
  });

  it('names the classes the stylesheet defines, and none for no attention', () => {
    expect(attentionClass('stale')).toBe('attention attention-stale');
    expect(attentionClass('over')).toBe('attention attention-over');
    expect(attentionClass('limited')).toBe('attention attention-limited');
    expect(attentionClass('closed')).toBe('attention attention-closed');
    expect(attentionClass(null)).toBe('');
  });
});
