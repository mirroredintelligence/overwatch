// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getDone, markDone } from './progress';

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('lesson progress', () => {
  it('remembers a lesson marked done, and gives it back', () => {
    markDone('correct-a-figure');

    expect(getDone().has('correct-a-figure')).toBe(true);
  });

  it('answers an empty set, and throws nothing, when localStorage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    expect(() => markDone('correct-a-figure')).not.toThrow();
    expect(getDone().size).toBe(0);
  });
});
