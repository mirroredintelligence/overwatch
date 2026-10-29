import type { Server } from 'node:http';
import { startMockBackend } from './support/backend';
import { startFakeEntraServer } from './support/oidc';

// Starts the stand-in back end and the fake Entra provider before the browser tests and stops them after.
export default async function globalSetup() {
  const servers: Server[] = [await startMockBackend(), await startFakeEntraServer()];
  return async () => {
    for (const server of servers) {
      // Event streams stay open until closed.
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  };
}
