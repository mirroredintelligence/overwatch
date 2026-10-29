import type { BoardEntry } from '@/lib/board/types';

// Stub (DEC-010): the red commit holds this so the tests fail on an assertion.
export function Tile({ entry, now }: { entry: BoardEntry; now: string | Date }) {
  void entry;
  void now;
  return <article data-el="WALL-TILE" />;
}
