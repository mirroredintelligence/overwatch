import { describe, expect, it } from 'vitest';
import { BOARD_A } from '@/test/fixtures/board';
import { parseBoardJson } from './boardJson';

// TEN-072: a network's board reaches the wall as a Board whose rows may also say which organisation they
// are from, whether it is the viewer's own, and whether the listing is paused.

describe('parseBoardJson: the network wall board', () => {
  const entry = { ...BOARD_A.entries[0]!, organisation: 'Sample Area B', ownOrganisation: false, paused: false };

  it('keeps the organisation, the own-organisation flag and the paused flag of a row', () => {
    const board = parseBoardJson({ ...BOARD_A, entries: [entry] });
    expect(board.entries[0]).toMatchObject({ organisation: 'Sample Area B', ownOrganisation: false, paused: false });
  });

  it('reads a row of the wall’s own board, which has none of them', () => {
    const board = parseBoardJson(BOARD_A);
    expect(board.entries[0]?.organisation).toBeUndefined();
    expect(board.entries[0]?.paused).toBeUndefined();
  });

  it.each([
    ['an organisation that is a number', { organisation: 4 }],
    ['an own flag that is text', { ownOrganisation: 'yes' }],
    ['a paused flag that is text', { paused: 'yes' }],
  ])('refuses %s', (_name, over) => {
    expect(() => parseBoardJson({ ...BOARD_A, entries: [{ ...entry, ...over }] })).toThrow();
  });
});
