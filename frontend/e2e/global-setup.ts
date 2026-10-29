import type { Server } from 'node:http';
import { startMockBackend } from './support/backend';

// Starts the stand-in back end before the browser tests and stops it after.
export default async function globalSetup() {
  const server: Server = await startMockBackend();
  return async () => {
    // Event streams stay open until closed.
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  };
}
