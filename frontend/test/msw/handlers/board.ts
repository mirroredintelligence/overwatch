import { http, HttpResponse } from 'msw';
import type { Board } from '@/lib/board/types';
import { BOARD_A, BOARD_B, boardParameters } from '@/test/fixtures/board';

// The back end's `$board`, for tests. The board that comes back depends only on
// the bearer token, as it does on the real back end: the token is the one thing
// that says which organisation is asking.

export const BACKEND_BASE = 'http://backend.test/fhir';
export const BOARD_URL = `${BACKEND_BASE}/HealthcareService/$board`;

export const TOKEN_ORG_A = 'token-for-organisation-a';
export const TOKEN_ORG_B = 'token-for-organisation-b';

const BOARDS: Record<string, Board> = {
  [TOKEN_ORG_A]: BOARD_A,
  [TOKEN_ORG_B]: BOARD_B,
};

const FHIR_JSON = 'application/fhir+json; fhirVersion=4.3';

/** Every `$board` request this test file's handlers saw, newest last. */
export const seenBoardRequests: Request[] = [];

export function resetSeenBoardRequests() {
  seenBoardRequests.length = 0;
}

export const boardHandlers = [
  http.get(BOARD_URL, ({ request }) => {
    seenBoardRequests.push(request.clone());
    const token = /^Bearer (.+)$/.exec(request.headers.get('authorization') ?? '')?.[1];
    const board = token === undefined ? undefined : BOARDS[token];
    if (board === undefined) {
      return HttpResponse.json(
        { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] },
        { status: 401, headers: { 'Content-Type': FHIR_JSON } },
      );
    }
    return HttpResponse.json(boardParameters(board), {
      headers: { 'Content-Type': FHIR_JSON, 'Cache-Control': 'no-store' },
    });
  }),
];
