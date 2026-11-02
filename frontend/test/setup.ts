import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, expect } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import { backendEdge, installBackendEdge } from './backend-edge';
import { canary, installLeakCanary } from './leak-canary';
import { handlers } from './msw/handlers';
import { server } from './msw/server';

expect.extend(axeMatchers);

// Node 26 ships its own `localStorage` and `sessionStorage` (experimental web storage), and with no
// `--localstorage-file` they are undefined: they shadow jsdom's and every test that touches storage fails on that
// Node. When the environment's storage is not usable, give the tests jsdom's own (or, failing that, a plain in-memory one).
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key: string) => data.get(String(key)) ?? null,
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => void data.delete(String(key)),
    setItem: (key: string, value: string) => void data.set(String(key), String(value)),
  } as Storage;
}

// Tests that run in the plain Node environment have no window and no storage to repair.
for (const name of typeof window === 'undefined' ? [] : (['localStorage', 'sessionStorage'] as const)) {
  let usable = false;
  try {
    usable = typeof window[name]?.getItem === 'function';
  } catch {
    usable = false;
  }
  if (!usable) {
    // jsdom's own storage is the real thing (tests spy on `Storage.prototype`); the plain one is the last resort.
    const own = (globalThis as { jsdom?: { window: Window } }).jsdom?.window;
    let jsdomStore: Storage | undefined;
    try {
      jsdomStore = own?.[name];
    } catch {
      jsdomStore = undefined;
    }
    const store = jsdomStore ?? memoryStorage();
    for (const target of [window, globalThis]) {
      Object.defineProperty(target, name, { value: store, configurable: true, writable: true });
    }
  }
}

// Every request a test makes must have a handler. An unmocked request fails
// the test instead of reaching the network.
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  // The default handlers are in place for the first test too, not only after
  // the first afterEach (W05: the first test of a file saw none).
  server.resetHandlers(...handlers);
  // Every call to the back end is watched for a tenant leak (test/leak-canary.ts).
  installLeakCanary(server);
  // And for the back end's body-type rule: a POST or PUT with no JSON Content-Type is a 415 there.
  installBackendEdge(server);
});

// Each test starts with the default handlers only.
afterEach(() => {
  server.resetHandlers(...handlers);
});

// A test that made a call that could cross a tenant fails here, whatever it was checking.
afterEach(() => {
  try {
    canary.assertClean();
  } finally {
    canary.reset();
  }
});

// A call the real back end would refuse (415) fails the test that made it, even when the test mocks the answer.
afterEach(() => {
  try {
    backendEdge.assertClean();
  } finally {
    backendEdge.reset();
  }
});

afterAll(() => {
  server.close();
});

// Vitest does not run Testing Library's automatic cleanup (no globals), so
// unmount after each test to stop renders leaking into the next test.
afterEach(() => {
  cleanup();
});
