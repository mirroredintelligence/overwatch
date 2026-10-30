import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { Board } from '@/lib/board/types';
import { BOARD_A, BOARD_SURGE, boardBuiltAt, boardParameters, withForeignOrganisation } from '@/test/fixtures/board';
import { fakeBackendToken } from '@/test/backendToken';
import { BACKEND_PORT, E2E_TENANT } from './env';
import { BOARDS_BY_TOKEN, LIVE_SURGE_PREFIX, LIVE_TOKEN_PREFIX, TOKEN_FOREIGN_ENTRY } from './tokens';
import { handleLinkRoute } from './links';

// A stand-in for the back end, for the browser tests. Like the real one it answers
// by bearer token alone and reads nothing else from the request: GET $board and
// GET /events (server-sent events). Tokens that start with LIVE_TOKEN_PREFIX get a
// private, controllable state, so parallel tests never touch each other's:
//
//   POST /__control/<token>  { mode, streamDown, emit, drop, ucrWestFree }
//   GET  /__state/<token>    { boardRequests, streamOpens, streamRefusals, openStreams }
//
// Every board is built "now" (shifted from the sample board), because the wall
// judges a board by the clock: a board dated last week is Last known.

export type Mode = 'ok' | 'down' | 'malformed' | 'stale';

type LiveState = {
  mode: Mode;
  streamDown: boolean;
  ucrWestFree: number;
  boardRequests: number;
  streamOpens: number;
  streamRefusals: number;
  streams: Set<ServerResponse>;
};

const live = new Map<string, LiveState>();

function stateFor(token: string): LiveState {
  let state = live.get(token);
  if (!state) {
    state = { mode: 'ok', streamDown: false, ucrWestFree: 4, boardRequests: 0, streamOpens: 0, streamRefusals: 0, streams: new Set() };
    live.set(token, state);
  }
  return state;
}

function bearer(request: IncomingMessage): string | undefined {
  return /^Bearer (.+)$/.exec(request.headers.authorization ?? '')?.[1];
}

function boardFor(token: string, state: LiveState | undefined): Board | undefined {
  const live = token.startsWith(LIVE_TOKEN_PREFIX);
  const base = live ? (token.startsWith(LIVE_SURGE_PREFIX) ? BOARD_SURGE : BOARD_A) : BOARDS_BY_TOKEN[token];
  if (base === undefined) return undefined;
  const built = state?.mode === 'stale' ? new Date(Date.now() - 20 * 60_000) : new Date();
  const board = boardBuiltAt(base, built.toISOString());
  if (state !== undefined && base === BOARD_A) {
    board.entries = board.entries.map((e) =>
      e.serviceId === 'svc-ucr-west'
        ? { ...e, effectiveAvailable: state.ucrWestFree, used: Math.max(0, e.established - state.ucrWestFree) }
        : e,
    );
  }
  return board;
}

function json(response: ServerResponse, status: number, body: unknown, type = 'application/json') {
  response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
}

function body(request: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    let text = '';
    request.on('data', (chunk: Buffer) => (text += chunk.toString()));
    request.on('end', () => {
      try {
        resolve(text ? (JSON.parse(text) as Record<string, unknown>) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function handleBoard(request: IncomingMessage, response: ServerResponse) {
  const token = bearer(request);
  const state = token?.startsWith(LIVE_TOKEN_PREFIX) ? stateFor(token) : undefined;
  const board = token === undefined ? undefined : boardFor(token, state);
  if (token === undefined || board === undefined) {
    json(response, 401, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }, 'application/fhir+json');
    return;
  }
  if (state) state.boardRequests += 1;
  if (state?.mode === 'down') {
    json(response, 503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'transient' }] }, 'application/fhir+json');
    return;
  }
  if (state?.mode === 'malformed') {
    const parameters = boardParameters(board);
    const first = parameters.parameter?.[0].part?.find((p) => p.name === 'status');
    if (first) first.valueCode = 'busy';
    json(response, 200, parameters, 'application/fhir+json');
    return;
  }
  const parameters = boardParameters(board);
  json(response, 200, token === TOKEN_FOREIGN_ENTRY ? withForeignOrganisation(parameters) : parameters, 'application/fhir+json');
}

function handleEvents(request: IncomingMessage, response: ServerResponse) {
  const token = bearer(request);
  const known = token !== undefined && (token.startsWith(LIVE_TOKEN_PREFIX) || BOARDS_BY_TOKEN[token] !== undefined);
  if (!known) {
    json(response, 401, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }, 'application/fhir+json');
    return;
  }
  const state = token.startsWith(LIVE_TOKEN_PREFIX) ? stateFor(token) : undefined;
  if (state?.streamDown) {
    state.streamRefusals += 1;
    json(response, 503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'transient' }] }, 'application/fhir+json');
    return;
  }
  response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
  response.write(': keep-alive\n\n');
  if (state) {
    state.streamOpens += 1;
    state.streams.add(response);
    response.on('close', () => state.streams.delete(response));
  }
}

async function handleControl(request: IncomingMessage, response: ServerResponse, token: string) {
  const state = stateFor(token);
  const change = await body(request);
  if (typeof change.mode === 'string') state.mode = change.mode as Mode;
  if (typeof change.streamDown === 'boolean') state.streamDown = change.streamDown;
  if (typeof change.ucrWestFree === 'number') state.ucrWestFree = change.ucrWestFree;
  if (change.drop === true) for (const stream of [...state.streams]) stream.end();
  if (change.emit === true) {
    for (const stream of state.streams) {
      stream.write(`event: board\ndata: {"serviceId":"svc-ucr-west","changedAt":"${new Date().toISOString()}"}\n\n`);
    }
  }
  json(response, 200, { ok: true });
}

// The back end's token exchange (TEN-043) for the staff sign-in: the tenant is the Host the request
// was addressed to (here the one e2e tenant), the identity token's directory must be the one that
// tenant has bound, and the role comes from the identity's app roles. The reads of the identity token
// here are claims only: the real back end verifies its signature. Every refusal is one 403.
const ROLE_FOR_APP_ROLE: Record<string, string> = {
  'DIUCS.Lead': 'lead',
  'DIUCS.Clinical': 'clinical',
  'DIUCS.Advisor': 'advisor',
  'DIUCS.Owner': 'owner',
  'DIUCS.Planning': 'exec',
};

async function handleExchange(request: IncomingMessage, response: ServerResponse) {
  const send = (status: number, payload: unknown) => json(response, status, payload);
  if (request.headers.host?.toLowerCase() !== E2E_TENANT.host) return send(404, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] });
  const { idToken } = (await body(request)) as { idToken?: unknown };
  if (typeof idToken !== 'string') return send(400, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] });
  let claims: Record<string, unknown> = {};
  try {
    claims = JSON.parse(Buffer.from(idToken.split('.')[1] ?? '', 'base64url').toString('utf8')) as Record<string, unknown>;
  } catch {
    claims = {};
  }
  const held = new Set((Array.isArray(claims.roles) ? claims.roles : []).map((r) => ROLE_FOR_APP_ROLE[String(r)]).filter(Boolean));
  const role = ['lead', 'clinical', 'advisor', 'owner', 'exec'].find((candidate) => held.has(candidate));
  if (String(claims.tid ?? '').toLowerCase() !== E2E_TENANT.directoryId || role === undefined) {
    return send(403, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden', diagnostics: 'Your account does not have access.' }] });
  }
  const now = new Date();
  const exp = Math.floor(now.getTime() / 1000) + 8 * 3600;
  const token = fakeBackendToken({ sub: `stf-${String(claims.oid ?? '').slice(0, 8)}`.padEnd(36, '0'), role, tenant: E2E_TENANT.id, exp }, now);
  send(200, { token, expiresAt: new Date(exp * 1000).toISOString(), role });
}

export function startMockBackend(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const control = /^\/__control\/(.+)$/.exec(url.pathname);
    const stateRoute = /^\/__state\/(.+)$/.exec(url.pathname);

    if (request.method === 'POST' && url.pathname === '/auth/token') {
      void handleExchange(request, response);
    } else if (url.pathname.startsWith('/links/')) {
      void handleLinkRoute(request, response, url.pathname).then((handled) => {
        if (!handled) response.writeHead(404).end();
      });
    } else if (request.method === 'POST' && control) {
      void handleControl(request, response, decodeURIComponent(control[1]));
    } else if (request.method === 'GET' && stateRoute) {
      const state = stateFor(decodeURIComponent(stateRoute[1]));
      json(response, 200, {
        boardRequests: state.boardRequests,
        streamOpens: state.streamOpens,
        streamRefusals: state.streamRefusals,
        openStreams: state.streams.size,
      });
    } else if (request.method === 'GET' && url.pathname === '/fhir/HealthcareService/$board') {
      handleBoard(request, response);
    } else if (request.method === 'GET' && url.pathname === '/fhir/events') {
      handleEvents(request, response);
    } else {
      response.writeHead(404).end();
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
