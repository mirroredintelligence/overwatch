import type { Board } from '@/lib/board/types';
import { BOARD_A, BOARD_B } from '@/test/fixtures/board';

export const TOKEN_ORG_A = 'e2e-token-for-organisation-a';
export const TOKEN_ORG_B = 'e2e-token-for-organisation-b';

export const BOARDS_BY_TOKEN: Record<string, Board> = {
  [TOKEN_ORG_A]: BOARD_A,
  [TOKEN_ORG_B]: BOARD_B,
};

/** Tokens that start with this get their own controllable back end state (e2e/support/backend.ts). */
export const LIVE_TOKEN_PREFIX = 'e2e-live-';
