import type { Board as BoardData } from '@/lib/board/types';

// Stub (DEC-010).
export function Board({ board }: { board: BoardData }) {
  void board;
  return <main />;
}
