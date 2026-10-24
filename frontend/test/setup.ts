import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, expect } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';

expect.extend(axeMatchers);

// Vitest does not run Testing Library's automatic cleanup (no globals), so
// unmount after each test to stop renders leaking into the next test.
afterEach(() => {
  cleanup();
});
