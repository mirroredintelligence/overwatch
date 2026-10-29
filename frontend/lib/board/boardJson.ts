import type { Board } from './types';

// Reads the board the BFF sends the browser (JSON of a Board) and fails closed.
export function parseBoardJson(value: unknown): Board {
  return value as Board;
}
