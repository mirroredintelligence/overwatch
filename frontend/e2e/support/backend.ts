import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { boardParameters } from '@/test/fixtures/board';
import { BACKEND_PORT } from './env';
import { BOARDS_BY_TOKEN } from './tokens';

// A stand-in for the back end's `$board`, for the browser tests. Like the real
// one it answers by bearer token alone and reads nothing else from the request.

export function startMockBackend(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const token = /^Bearer (.+)$/.exec(request.headers.authorization ?? '')?.[1];
    const board = token === undefined ? undefined : BOARDS_BY_TOKEN[token];

    if (request.method !== 'GET' || url.pathname !== '/fhir/HealthcareService/$board') {
      response.writeHead(404).end();
    } else if (board === undefined) {
      response
        .writeHead(401, { 'Content-Type': 'application/fhir+json' })
        .end(JSON.stringify({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }));
    } else {
      response
        .writeHead(200, { 'Content-Type': 'application/fhir+json', 'Cache-Control': 'no-store' })
        .end(JSON.stringify(boardParameters(board)));
    }
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(BACKEND_PORT, '127.0.0.1', () => resolve(server));
  });
}

export function port(server: Server): number {
  return (server.address() as AddressInfo).port;
}
