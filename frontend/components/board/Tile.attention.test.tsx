import { render, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { BoardEntry } from '@/lib/board/types';
import { MAIN_ENTRIES, NOW, UCR_WEST, VIRTUAL_WARD } from '@/test/fixtures/board';
import { Tile } from './Tile';

// DEC-1365: the attention glow, on the advisor's board only. It is added to the shape and word, never instead.

function tile(container: HTMLElement): HTMLElement {
  const found = container.querySelector<HTMLElement>('[data-el="WALL-TILE"]');
  if (!found) throw new Error('no tile was rendered');
  return found;
}

const byStatus = (status: string) => MAIN_ENTRIES.find((e) => e.status === status) as BoardEntry;

describe('Tile: the attention glow (DEC-1365)', () => {
  it('adds no glow by default (the wall)', () => {
    for (const e of [UCR_WEST, VIRTUAL_WARD, ...MAIN_ENTRIES]) {
      const { container, unmount } = render(<Tile entry={e} now={NOW} />);
      expect(tile(container).className).not.toContain('attention');
      expect(tile(container).getAttribute('data-attention')).toBeNull();
      unmount();
    }
  });

  it.each([
    ['not-updated', VIRTUAL_WARD, 'stale'],
    ['over-capacity', byStatus('over-capacity'), 'over'],
    ['limited', byStatus('limited'), 'limited'],
    ['not-accepting', byStatus('not-accepting'), 'closed'],
  ])('a %s tile has the %s glow, and still its status shape and word', (status, entry, glow) => {
    const { container } = render(<Tile entry={entry} now={NOW} attention />);
    const el = tile(container);
    expect(el.className).toContain(`attention attention-${glow}`);
    expect(el.getAttribute('data-attention')).toBe(glow);
    expect(el.getAttribute('data-status')).toBe(status);
    expect(el.querySelector('[data-shape]')).not.toBeNull();
  });

  it('an accepting tile has no glow', () => {
    const { container } = render(<Tile entry={UCR_WEST} now={NOW} attention />);
    expect(tile(container).getAttribute('data-attention')).toBeNull();
  });

  it('a last known tile glows stale whatever it last said, and so does a paused listing', () => {
    const over = byStatus('over-capacity');
    const last = render(<Tile entry={over} now={NOW} lastKnown attention />);
    expect(tile(last.container).getAttribute('data-attention')).toBe('stale');
    last.unmount();
    const paused = render(<Tile entry={{ ...over, paused: true }} now={NOW} attention />);
    expect(tile(paused.container).getAttribute('data-attention')).toBe('stale');
  });

  it('an old figure glows stale even when it said accepting, and still shows its figure and the word old', () => {
    const { container } = render(<Tile entry={{ ...UCR_WEST, reportedAt: '2026-10-23T10:00:00Z' }} now={NOW} attention />);
    const el = tile(container);
    expect(el.getAttribute('data-attention')).toBe('stale');
    expect(within(el).getByText(/· old$/)).toBeInTheDocument();
  });

  it('a stale tile never shows the last figure as spare capacity: the number is ? and "Phone to confirm"', () => {
    const { container } = render(<Tile entry={VIRTUAL_WARD} now={NOW} attention />);
    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')?.textContent).toBe('?');
    expect(within(tile(container)).getByText('Phone to confirm')).toBeInTheDocument();
  });
});
