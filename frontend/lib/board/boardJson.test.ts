import { describe, expect, it } from 'vitest';
import { BOARD_A, BOARD_B, entry } from '@/test/fixtures/board';
import { parseBoardJson } from './boardJson';
import { BoardParseError } from './parse';

// The board the BFF sends the browser is JSON, and the browser does not trust it
// more than the server trusts the back end: anything it cannot read is refused,
// so the wall falls back to Last known and never to a blank or wrong tile.

function roundTrip<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function withEntry(change: (e: Record<string, unknown>) => void): unknown {
  const board = roundTrip(BOARD_B) as unknown as { entries: Record<string, unknown>[] };
  change(board.entries[0]);
  return board;
}

describe('parseBoardJson', () => {
  it('reads a board as the BFF sends it, entry order kept', () => {
    expect(parseBoardJson(roundTrip(BOARD_A))).toEqual(BOARD_A);
  });

  it('reads an entry whose optional values are null, and a board with no organisation', () => {
    const sparse = {
      ...BOARD_B,
      organisation: null,
      entries: [
        entry({
          serviceId: 's1',
          name: 'S1',
          status: 'not-updated',
          effectiveAvailable: null,
          used: null,
          comment: null,
          reportedAt: null,
          nextDueAt: null,
          wasDueAt: null,
        }),
      ],
    };
    expect(parseBoardJson(roundTrip(sparse))).toEqual(sparse);
  });

  it('keeps a zero count', () => {
    const board = withEntry((e) => {
      e.used = 0;
      e.pending = 0;
    });
    expect(parseBoardJson(board).entries[0]).toMatchObject({ used: 0, pending: 0 });
  });

  it('gives an empty board, not an error, when there are no services', () => {
    expect(parseBoardJson({ ...roundTrip(BOARD_B), entries: [] }).entries).toEqual([]);
  });

  it('leaves out fields it does not know, so nothing unexpected is carried to the screen', () => {
    const board = withEntry((e) => {
      e.patientName = 'not for the wall';
    }) as Record<string, unknown>;
    board.extra = 'x';
    const parsed = parseBoardJson(board);
    expect(JSON.stringify(parsed)).not.toContain('not for the wall');
    expect(parsed).not.toHaveProperty('extra');
  });

  it.each([
    ['null', null],
    ['a string', 'board'],
    ['an array', []],
    ['a number', 7],
    ['an empty object', {}],
    ['a FHIR Parameters resource', { resourceType: 'Parameters', parameter: [] }],
  ])('fails closed on %s', (_label, value) => {
    expect(() => parseBoardJson(value)).toThrow(BoardParseError);
  });

  it.each(['entries', 'pressure', 'allLimitedOrWorse', 'generatedAt'])('fails closed when %s is missing', (key) => {
    const board = roundTrip(BOARD_B) as unknown as Record<string, unknown>;
    delete board[key];
    expect(() => parseBoardJson(board)).toThrow(BoardParseError);
  });

  it('fails closed when entries is not a list, or an entry is not an object', () => {
    expect(() => parseBoardJson({ ...roundTrip(BOARD_B), entries: 'none' })).toThrow(BoardParseError);
    expect(() => parseBoardJson({ ...roundTrip(BOARD_B), entries: [null] })).toThrow(BoardParseError);
    expect(() => parseBoardJson({ ...roundTrip(BOARD_B), entries: ['x'] })).toThrow(BoardParseError);
  });

  it('fails closed on a status it does not know', () => {
    expect(() => parseBoardJson(withEntry((e) => (e.status = 'available')))).toThrow(BoardParseError);
    expect(() => parseBoardJson(withEntry((e) => (e.status = 'toString')))).toThrow(BoardParseError);
  });

  it.each(['effectiveAvailable', 'overBy', 'used', 'established', 'pending'])(
    'fails closed on a negative %s',
    (key) => {
      expect(() => parseBoardJson(withEntry((e) => (e[key] = -3)))).toThrow(BoardParseError);
    },
  );

  it.each(['effectiveAvailable', 'overBy', 'used', 'established', 'pending'])(
    'fails closed on a fractional %s',
    (key) => {
      expect(() => parseBoardJson(withEntry((e) => (e[key] = 2.5)))).toThrow(BoardParseError);
    },
  );

  it('fails closed on a count that is not a number, or too large to be exact', () => {
    expect(() => parseBoardJson(withEntry((e) => (e.established = '8')))).toThrow(BoardParseError);
    expect(() => parseBoardJson(withEntry((e) => (e.established = Number.MAX_SAFE_INTEGER + 2)))).toThrow(
      BoardParseError,
    );
  });

  it.each(['serviceId', 'name', 'category', 'unitLabel'])('fails closed when %s is missing or not text', (key) => {
    expect(() => parseBoardJson(withEntry((e) => delete e[key]))).toThrow(BoardParseError);
    expect(() => parseBoardJson(withEntry((e) => (e[key] = 7)))).toThrow(BoardParseError);
  });

  it.each(['reportedAt', 'nextDueAt', 'wasDueAt'])('fails closed when %s is not a time', (key) => {
    expect(() => parseBoardJson(withEntry((e) => (e[key] = 'yesterday')))).toThrow(BoardParseError);
    expect(() => parseBoardJson(withEntry((e) => (e[key] = 12)))).toThrow(BoardParseError);
  });

  it('fails closed when comment is neither text nor null, or an optional count is neither a count nor null', () => {
    expect(() => parseBoardJson(withEntry((e) => (e.comment = 5)))).toThrow(BoardParseError);
    expect(() => parseBoardJson(withEntry((e) => (e.used = 'many')))).toThrow(BoardParseError);
  });

  it('fails closed when the board time, pressure, flag or organisation is of the wrong type', () => {
    const base = roundTrip(BOARD_B) as unknown as Record<string, unknown>;
    expect(() => parseBoardJson({ ...base, generatedAt: 'now' })).toThrow(BoardParseError);
    expect(() => parseBoardJson({ ...base, generatedAt: 1_700_000_000 })).toThrow(BoardParseError);
    expect(() => parseBoardJson({ ...base, pressure: 3 })).toThrow(BoardParseError);
    expect(() => parseBoardJson({ ...base, allLimitedOrWorse: 'no' })).toThrow(BoardParseError);
    expect(() => parseBoardJson({ ...base, organisation: 4 })).toThrow(BoardParseError);
  });

  it('puts nothing from the body in the error message', () => {
    const attempt = () => parseBoardJson(withEntry((e) => (e.status = 'Secret Ward 7')));
    expect(attempt).toThrow(BoardParseError);
    expect(attempt).not.toThrow(/Secret Ward 7/);
  });
});
