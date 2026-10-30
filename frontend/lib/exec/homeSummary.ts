// Stub (W40 red).
import type { Board, BoardEntry } from '@/lib/board/types';
export function needsAttention(board: Board): BoardEntry[] {
  void board;
  throw new Error('not implemented');
}
export function limitedOrWorse(board: Board): { limited: number; inHours: number } {
  void board;
  throw new Error('not implemented');
}
export function pressureChip(pressure: string): { label: string; word: string } {
  void pressure;
  throw new Error('not implemented');
}
export function attentionLine(entry: BoardEntry, now: string): string {
  void entry; void now;
  throw new Error('not implemented');
}
