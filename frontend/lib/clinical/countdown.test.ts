import { describe, expect, it } from 'vitest';
import { minutesLeft } from './countdown';

describe('minutesLeft', () => {
  it('returns 9 for 9 minutes 30 seconds left, counting whole minutes', () => {
    expect(minutesLeft('2026-10-23T13:30:00Z', '2026-10-23T13:20:30Z')).toBe(9);
  });

  it('returns 0 once the return time has passed', () => {
    expect(minutesLeft('2026-10-23T13:30:00Z', '2026-10-23T13:31:00Z')).toBe(0);
  });

  it('is never negative, and refuses a time it cannot read', () => {
    expect(minutesLeft('2026-10-23T13:30:00Z', '2026-10-23T14:30:00Z')).toBe(0);
    expect(() => minutesLeft('not a time', '2026-10-23T13:30:00Z')).toThrow('returnsAt is not a time');
  });
});
