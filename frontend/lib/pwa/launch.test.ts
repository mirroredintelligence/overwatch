import { describe, expect, it } from 'vitest';
import { SPLASH_FLAG, takeLaunchSplash } from './launch';

function storage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size;
    },
  };
}

const standalone = ((query: string) => ({ matches: query === '(display-mode: standalone)' }) as MediaQueryList) as Window['matchMedia'];
const browserTab = (() => ({ matches: false }) as MediaQueryList) as Window['matchMedia'];

describe('takeLaunchSplash', () => {
  it('is true once in the installed app, then false for the rest of the session', () => {
    const sessionStorage = storage();
    expect(takeLaunchSplash({ matchMedia: standalone, sessionStorage })).toBe(true);
    expect(sessionStorage.getItem(SPLASH_FLAG)).toBe('1');
    expect(takeLaunchSplash({ matchMedia: standalone, sessionStorage })).toBe(false);
  });

  it('is true in an iOS home-screen app, which reports navigator.standalone', () => {
    expect(takeLaunchSplash({ matchMedia: browserTab, navigator: { standalone: true }, sessionStorage: storage() })).toBe(true);
  });

  it('is false in a browser tab, and leaves the session unmarked', () => {
    const sessionStorage = storage();
    expect(takeLaunchSplash({ matchMedia: browserTab, sessionStorage })).toBe(false);
    expect(sessionStorage.getItem(SPLASH_FLAG)).toBeNull();
  });

  it('is false when storage is missing or throws, or matchMedia is missing', () => {
    expect(takeLaunchSplash({ matchMedia: standalone })).toBe(false);
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => undefined } as unknown as Storage;
    expect(takeLaunchSplash({ matchMedia: standalone, sessionStorage: broken })).toBe(false);
    expect(takeLaunchSplash({ sessionStorage: storage() })).toBe(false);
  });
});

