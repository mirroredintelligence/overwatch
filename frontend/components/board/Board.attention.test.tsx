import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BOARD_SURGE } from '@/test/fixtures/board';
import { Board } from './Board';

// DEC-1365: the glow belongs to the advisor's view of the board; the wall (/screen) has none.

const START = <button type="button">Start a new call</button>;

describe('Board: the attention glow belongs to the advisor view (DEC-1365)', () => {
  it('marks over-capacity, limited and not-accepting tiles, and keeps the back end order (no ranking by status)', () => {
    const { container } = render(<Board board={BOARD_SURGE} view="advisor" action={START} />);
    const tiles = [...container.querySelectorAll('[data-el="WALL-TILE"]')];
    expect(tiles.map((t) => t.getAttribute('data-service-id'))).toEqual(BOARD_SURGE.entries.map((e) => e.serviceId));
    const glows = new Set(tiles.map((t) => t.getAttribute('data-attention')));
    expect(glows.has('over')).toBe(true);
    expect(glows.has('limited')).toBe(true);
    expect(glows.has('closed')).toBe(true);
  });

  it('the wall view has no glow on any tile', () => {
    const { container } = render(<Board board={BOARD_SURGE} />);
    expect(container.querySelectorAll('[data-attention]')).toHaveLength(0);
    expect(container.querySelectorAll('.attention')).toHaveLength(0);
  });
});
