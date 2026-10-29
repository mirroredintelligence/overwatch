import { http, HttpResponse } from 'msw';
import type { Board } from '@/lib/board/types';
import {
  BOARD_A,
  BOARD_B,
  BOARD_QUIET,
  BOARD_SURGE,
  boardParameters,
  withForeignOrganisation,
} from '@/test/fixtures/board';

// The back end's `$board`, for tests. The board that comes back depends only on
// the bearer token, as it does on the real back end: the token is the one thing
// that says which organisation is asking.

export const BACKEND_BASE = 'http://backend.test/fhir';
export const BOARD_URL = `${BACKEND_BASE}/HealthcareService/$board`;

export const TOKEN_ORG_A = 'token-for-organisation-a';
export const TOKEN_ORG_B = 'token-for-organisation-b';
// The "BoardSurge" and "BoardQuiet" artboards (W07), for organisation A.
export const TOKEN_SURGE = 'token-for-the-surge-board';
export const TOKEN_QUIET = 'token-for-the-quiet-board';
// A board whose payload names another organisation on an entry. A back end that
// worked must never send it; the wall must not show it.
export const TOKEN_FOREIGN_ENTRY = 'token-for-a-payload-with-a-foreign-organisation';

const BOARDS: Record<string, Board> = {
  [TOKEN_ORG_A]: BOARD_A,
  [TOKEN_ORG_B]: BOARD_B,
  [TOKEN_SURGE]: BOARD_SURGE,
  [TOKEN_QUIET]: BOARD_QUIET,
  [TOKEN_FOREIGN_ENTRY]: BOARD_A,
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
    const parameters = boardParameters(board);
    return HttpResponse.json(token === TOKEN_FOREIGN_ENTRY ? withForeignOrganisation(parameters) : parameters, {
      headers: { 'Content-Type': FHIR_JSON, 'Cache-Control': 'no-store' },
    });
  }),
];
