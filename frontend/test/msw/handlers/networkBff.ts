import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import {
  BOARD_BODY,
  CRITERIA_BODY,
  DIRECTORY_BODY,
  DIRECTORY_HISTORY_BODY,
  NETWORKS_BODY,
  OWN_ORGANISATION,
  PHONES_BODY,
  SYSTEM_NOW_BODY,
  WEEK_BODY,
} from '@/test/fixtures/network';
import { parseBoard, parseCriteria, parseDirectory, parseNetworks, parsePhones, parseSystemNow, parseWeek } from '@/lib/network/parse';

// The app's own BFF routes for the network pages (`/api/bff/network...`), for component tests. Each
// answers what the real route answers: the back end's body run through the same parser the route uses,
// so the shape of every answer is the shape the pages get. A test that needs another answer uses
// server.use(...). Every request is kept, with its query.

export type SeenNetworkBff = { path: string; query: string };
export const seenNetworkBff: SeenNetworkBff[] = [];
export function resetNetworkBff(): void {
  seenNetworkBff.length = 0;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

function answer(path: string, body: () => unknown): HttpResponseResolver {
  return ({ request }) => {
    const url = new URL(request.url);
    seenNetworkBff.push({ path, query: url.search.slice(1) });
    return HttpResponse.json(body() as Record<string, unknown>, { headers: NO_STORE });
  };
}

/** The list of networks the BFF answers: the organisation's own name and the networks it may see. */
export const NETWORK_LIST = { ownOrganisation: OWN_ORGANISATION, networks: parseNetworks(NETWORKS_BODY, 'backend') };

export const networkBffHandlers = [
  http.get('/api/bff/network', answer('/api/bff/network', () => NETWORK_LIST)),
  http.get('/api/bff/network/board', answer('/api/bff/network/board', () => parseBoard(BOARD_BODY, 'backend'))),
  http.get(
    '/api/bff/network/directory',
    answer('/api/bff/network/directory', () => parseDirectory(DIRECTORY_BODY, 'backend')),
  ),
  http.get(
    '/api/bff/network/criteria',
    answer('/api/bff/network/criteria', () => parseCriteria(CRITERIA_BODY, 'backend')),
  ),
  http.get(
    '/api/bff/network/system-now',
    answer('/api/bff/network/system-now', () => parseSystemNow(SYSTEM_NOW_BODY, 'backend')),
  ),
  http.get('/api/bff/network/phones', answer('/api/bff/network/phones', () => parsePhones(PHONES_BODY, 'backend'))),
  http.get('/api/bff/network/week', answer('/api/bff/network/week', () => parseWeek(WEEK_BODY, 'backend'))),
];

/** The directory read with `history=true`, for the history page's tests. */
export const historyDirectory = parseDirectory(DIRECTORY_HISTORY_BODY, 'backend');
