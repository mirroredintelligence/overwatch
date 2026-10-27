import { setupServer } from 'msw/node';

// One MSW server for the whole test run. test/setup.ts starts and stops it.
export const server = setupServer();
