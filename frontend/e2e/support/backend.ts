import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { Board } from '@/lib/board/types';
import { BOARD_A, BOARD_SURGE, boardBuiltAt, boardParameters, withForeignOrganisation } from '@/test/fixtures/board';
import { BACKEND_PORT } from './env';
import { BOARDS_BY_TOKEN, LIVE_SURGE_PREFIX, LIVE_TOKEN_PREFIX, TOKEN_FOREIGN_ENTRY } from './tokens';

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

export function startMockBackend(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://localhost');
    const control = /^\/__control\/(.+)$/.exec(url.pathname);
    const stateRoute = /^\/__state\/(.+)$/.exec(url.pathname);

    if (request.method === 'POST' && control) {
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
