import { describe, expect, it } from 'vitest';
import { MAX_RANGE_BYTES, parseRange } from './range';

describe('parseRange (DEC-1362)', () => {
  it('reads one closed range', () => {
    expect(parseRange('bytes=0-16383')).toEqual({ start: 0, end: 16383 });
    expect(parseRange(' bytes=1000-1999 ')).toEqual({ start: 1000, end: 1999 });
  });

  it.each([null, '', 'bytes=0-', 'bytes=-500', 'bytes=5-1', 'bytes=0-1,5-9', 'items=0-1', 'bytes=a-b', 'bytes=0-99999999999999'])(
    'refuses %j: the route cannot be asked for an open, reversed or many-part range',
    (header) => {
      expect(parseRange(header)).toBeNull();
    },
  );

  it('refuses a range longer than the cap, so the route cannot pull the whole file', () => {
    expect(parseRange(`bytes=0-${MAX_RANGE_BYTES - 1}`)).not.toBeNull();
    expect(parseRange(`bytes=0-${MAX_RANGE_BYTES}`)).toBeNull();
  });
});
