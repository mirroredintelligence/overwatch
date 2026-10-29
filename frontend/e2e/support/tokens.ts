import type { Board } from '@/lib/board/types';
import { BOARD_A, BOARD_B, BOARD_QUIET, BOARD_SURGE } from '@/test/fixtures/board';

export const TOKEN_ORG_A = 'e2e-token-for-organisation-a';
export const TOKEN_ORG_B = 'e2e-token-for-organisation-b';
// The "BoardSurge" and "BoardQuiet" artboards for organisation A (W07).
export const TOKEN_SURGE = 'e2e-token-for-the-surge-board';
export const TOKEN_QUIET = 'e2e-token-for-the-quiet-board';
// Organisation A's board, but the payload names another organisation on an entry.
export const TOKEN_FOREIGN_ENTRY = 'e2e-token-for-a-payload-with-a-foreign-organisation';

export const BOARDS_BY_TOKEN: Record<string, Board> = {
  [TOKEN_ORG_A]: BOARD_A,
  [TOKEN_ORG_B]: BOARD_B,
  [TOKEN_SURGE]: BOARD_SURGE,
  [TOKEN_QUIET]: BOARD_QUIET,
  [TOKEN_FOREIGN_ENTRY]: BOARD_A,
};

/** Tokens that start with this get their own controllable back end state (e2e/support/backend.ts). */
export const LIVE_TOKEN_PREFIX = 'e2e-live-';
/** A live token that starts with this serves the surge board instead of the sample board (W07). */
export const LIVE_SURGE_PREFIX = 'e2e-live-surge-';
