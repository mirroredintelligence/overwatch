import type { IncomingMessage, ServerResponse } from 'node:http';
import { BOARD_BODY, CRITERIA_BODY, DIRECTORY_BODY, DIRECTORY_HISTORY_BODY, NETWORKS_BODY, PHONES_BODY, SYSTEM_NOW_BODY, WEEK_BODY } from '@/test/fixtures/network';
import { TOKEN_ORG_A } from './tokens';

// The network routes of the stand-in back end, for the browser tests (TEN-068 to TEN-071, W17, W43,
// TEN-082). Like the real routes they answer from the bearer token only: organisation A's token is a member
// of the one network (`net-sample`, the id of NETWORKS_BODY); any other token is not, and every refusal is
// the one 404. The board is built "now" (the page judges a board by the clock). The stream sends a
// keep-alive and stays open.

const MEMBER_TOKENS = new Set([TOKEN_ORG_A]);
const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }] };
const NETWORK_ID = NETWORKS_BODY.networks[0]!.id;

function send(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
}

function bearer(request: IncomingMessage): string | undefined {
  return /^Bearer (.+)$/.exec(request.headers.authorization ?? '')?.[1];
}

/** Answers the network routes (at the root, not under /fhir) and returns true; false for any other path. */
export function handleNetworkRoute(request: IncomingMessage, response: ServerResponse, pathname: string, search: URLSearchParams): boolean {
  if (request.method !== 'GET') return false;
  const token = bearer(request);
  const member = token !== undefined && MEMBER_TOKENS.has(token);

  if (pathname === '/networks') {
    send(response, 200, member ? NETWORKS_BODY : { networks: [] });
    return true;
  }
  const route = /^\/network\/([^/]+)\/([a-z-]+)$/.exec(pathname);
  if (route === null) return false;
  if (!member || route[1] !== NETWORK_ID) {
    send(response, 404, NOT_FOUND);
    return true;
  }
  switch (route[2]) {
    case 'board':
      send(response, 200, { ...BOARD_BODY, generated_at: new Date().toISOString() });
      return true;
    case 'directory':
      send(response, 200, search.get('history') === 'true' ? DIRECTORY_HISTORY_BODY : DIRECTORY_BODY);
      return true;
    case 'criteria':
      send(response, 200, search.get('history') === 'true' ? { ...CRITERIA_BODY, entries: [] } : CRITERIA_BODY);
      return true;
    case 'system-now':
      send(response, 200, SYSTEM_NOW_BODY);
      return true;
    case 'phones':
      send(response, 200, PHONES_BODY);
      return true;
    case 'week':
      send(response, 200, WEEK_BODY);
      return true;
    case 'events':
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
      response.write(': keep-alive\n\n');
      request.on('close', () => response.end());
      return true;
    default:
      return false;
  }
}
