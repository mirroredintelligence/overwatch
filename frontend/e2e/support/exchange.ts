import type { IncomingMessage, ServerResponse } from 'node:http';
import { deviceExchange, staffExchange } from '@/test/fixtures/exchange';
import { DIRECTORY_A } from '@/test/oidc/constants';
import { SITE_PORT } from './env';

// The token exchange routes of the stand-in back end, for the browser tests (TEN-043). The answers
// come from the same table as the unit tests (test/fixtures/exchange.ts). The site is the one tenant
// host of a run: `localhost:<port>`, with directory A bound, so a person from any other directory is
// refused on it, as the real back end refuses a directory the host's tenant has not bound.

const GRANTS = { [`localhost:${SITE_PORT}`]: [DIRECTORY_A] };

function readJson(request: IncomingMessage): Promise<unknown> {
  return new Promise((resolve) => {
    let text = '';
    request.on('data', (chunk: Buffer) => (text += chunk.toString()));
    request.on('end', () => {
      try {
        resolve(text ? (JSON.parse(text) as unknown) : undefined);
      } catch {
        resolve(undefined);
      }
    });
  });
}

/** Answers `POST /auth/token` and `POST /auth/device-token` and returns true; false for any other path. */
export async function handleAuthRoute(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<boolean> {
  if (request.method !== 'POST' || !['/auth/token', '/auth/device-token'].includes(pathname)) return false;
  const body = await readJson(request);
  const host = request.headers.host ?? null;
  const reply =
    pathname === '/auth/token'
      ? staffExchange(host, body, new Date(), GRANTS)
      : deviceExchange(host, request.headers.authorization ?? null, body, new Date(), GRANTS);
  response.writeHead(reply.status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(reply.body));
  return true;
}
