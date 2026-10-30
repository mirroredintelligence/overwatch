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

  it('keeps the lessons through the storage helper: a namespaced key for this host, nothing else', () => {
    markDone('correct-a-figure');

    expect(window.localStorage.length).toBe(1);
    expect(window.localStorage.key(0)).toBe(`diucs:v1:${window.location.host}:learn.done`);
    expect(window.localStorage.getItem('diucs-learn-done')).toBeNull();
  });

  it('forgets the lessons when the device is wiped at sign-out (TEN-050)', async () => {
    markDone('correct-a-figure');
    const { wipeBrowserState } = await import('@/lib/session/signOut');
    await wipeBrowserState();

    expect(getDone().size).toBe(0);
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
