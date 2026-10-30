import type { IncomingMessage, ServerResponse } from 'node:http';
import { decodeJwt } from 'jose';
import { REVOKED_SCREENS } from '@/test/fixtures/exchange';
import { PairingStandIn } from '@/test/fixtures/pairing';
import { DIRECTORY_A } from '@/test/oidc/constants';
import { SITE_PORT } from './env';

// The wall screen pairing routes of the stand-in back end, for the browser tests (R15, DEC-224),
// from the same stand-in as the unit tests (test/fixtures/pairing.ts). The site is the one tenant
// host of a run, `localhost:<port>`.

const pairing = new PairingStandIn({ [`localhost:${SITE_PORT}`]: [DIRECTORY_A] });

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

function header(request: IncomingMessage, name: string): string | null {
  const value = request.headers[name];
  return typeof value === 'string' ? value : null;
}

/** True for a wall token the stand-in exchange issued for a screen no lead has disconnected: the board stand-in lets it read the sample board. */
export function isWallToken(token: string): boolean {
  try {
    const claims = decodeJwt(token);
    return claims.role === 'wall' && !REVOKED_SCREENS.has(String(claims.sub));
  } catch {
    return false;
  }
}

/** Answers `/screens/pairing`, `/screens/pairing/{id}`, `/screens` and `/screens/{id}/revoke`, and returns true; false for any other path. */
export async function handlePairingRoute(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<boolean> {
  const host = header(request, 'host');
  let reply;
  const claim = /^\/screens\/pairing\/([^/]+)$/.exec(pathname);
  const revoke = /^\/screens\/([^/]+)\/revoke$/.exec(pathname);
  if (request.method === 'POST' && pathname === '/screens/pairing') {
    reply = pairing.start(host);
  } else if (request.method === 'GET' && claim !== null) {
    reply = pairing.claim(host, decodeURIComponent(claim[1] ?? ''), header(request, 'x-screen-secret'));
  } else if (request.method === 'GET' && pathname === '/screens') {
    reply = pairing.list(host, header(request, 'authorization'));
  } else if (request.method === 'POST' && revoke !== null) {
    reply = pairing.revoke(host, header(request, 'authorization'), header(request, 'idempotency-key'), decodeURIComponent(revoke[1] ?? ''));
  } else if (request.method === 'POST' && pathname === '/screens') {
    reply = pairing.connect(host, header(request, 'authorization'), header(request, 'idempotency-key'), await readJson(request));
  } else {
    return false;
  }
  response.writeHead(reply.status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...reply.headers }).end(JSON.stringify(reply.body));
  return true;
}
