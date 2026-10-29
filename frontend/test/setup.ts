import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, expect } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';
import { handlers } from './msw/handlers';
import { server } from './msw/server';

expect.extend(axeMatchers);

// Every request a test makes must have a handler. An unmocked request fails
// the test instead of reaching the network.
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  // The default handlers are in place for the first test too, not only after
  // the first afterEach (W05: the first test of a file saw none).
  server.resetHandlers(...handlers);
});

// Each test starts with the default handlers only.
afterEach(() => {
  server.resetHandlers(...handlers);
});

afterAll(() => {
  server.close();
});

// Vitest does not run Testing Library's automatic cleanup (no globals), so
// unmount after each test to stop renders leaking into the next test.
afterEach(() => {
  cleanup();
});
