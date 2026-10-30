import { describe, expect, it } from 'vitest';
import type { Parameters, ParametersParameter } from '@/lib/fhir/types';
import {
  BOARD_A,
  BOARD_B,
  BOARD_QUIET,
  BOARD_SURGE,
  boardParameters,
  entry,
  entryParameter,
  GENERATED_AT,
  ORGANISATION_A,
  ORGANISATION_B,
  withForeignOrganisation,
} from '@/test/fixtures/board';
import { BoardParseError, parseBoardParameters } from './parse';

function part(parameters: Parameters, index: number): ParametersParameter[] {
  return parameters.parameter?.[index].part ?? [];
}

function without(parameters: Parameters, entryIndex: number, partName: string): Parameters {
  const copy = structuredClone(parameters);
  const target = copy.parameter?.[entryIndex];
  if (target?.part) target.part = target.part.filter((p) => p.name !== partName);
  return copy;
}

function withCountOn(parameters: Parameters, partName: string, value: number): Parameters {
  const copy = structuredClone(parameters);
  const target = copy.parameter?.[0].part?.find((p) => p.name === partName);
  if (!target) throw new Error(`the fixture has no ${partName} part`);
  delete target.valueInteger;
  target.valueInteger = value;
  return copy;
}

describe('parseBoardParameters', () => {
  it('maps a two-entry Parameters fixture to a Board, entry order kept', () => {
    const full = entry({
      serviceId: 'svc-one',
      name: 'Service one',
      comment: 'A comment',
      overBy: 2,
      wasDueAt: '2026-10-23T11:00:00Z',
    });
    const sparse = entry({
      serviceId: 'svc-two',
      name: 'Service two',
      status: 'not-updated',
      category: 'reablement',
      effectiveAvailable: null,
      used: null,
      comment: null,
      reportedAt: null,
      nextDueAt: null,
      wasDueAt: null,
    });
    const parameters: Parameters = {
      resourceType: 'Parameters',
      parameter: [
        entryParameter(full),
        entryParameter(sparse),
        { name: 'pressure', valueCode: 'watch' },
        { name: 'allLimitedOrWorse', valueBoolean: true },
        { name: 'generatedAt', valueDateTime: GENERATED_AT },
      ],
    };

    expect(parseBoardParameters(parameters)).toEqual({
      entries: [full, sparse],
      pressure: 'watch',
      allLimitedOrWorse: true,
      generatedAt: GENERATED_AT,
      organisation: null,
    });
  });

  it('turns every missing optional part into null, and keeps a zero as a zero', () => {
    const parsed = parseBoardParameters(
      boardParameters({
        ...BOARD_A,
        entries: [
          entry({
            serviceId: 'svc-zero',
            name: 'Zero',
            effectiveAvailable: 0,
            used: 0,
            overBy: null,
            comment: null,
            reportedAt: null,
            nextDueAt: null,
            wasDueAt: null,
          }),
        ],
      }),
    );

    expect(parsed.entries[0]).toMatchObject({
      effectiveAvailable: 0,
      used: 0,
      pending: 0,
      overBy: null,
      comment: null,
      reportedAt: null,
      nextDueAt: null,
      wasDueAt: null,
    });
  });

  it('reads the organisation display name when the back end sends it, and null when it does not', () => {
    expect(parseBoardParameters(boardParameters(BOARD_A)).organisation).toBe('Dorset');
    expect(parseBoardParameters(boardParameters(BOARD_B)).organisation).toBe('Neighbouring');
    expect(parseBoardParameters(boardParameters({ ...BOARD_A, organisation: null })).organisation).toBeNull();
  });

  it('reads the duty coordinator number when the back end sends it (DEC-777), and null when it sends none', () => {
    const parameters = boardParameters(BOARD_A);
    parameters.parameter?.push({ name: 'coordinationPhone', valueString: '01632 960001' });
    expect(parseBoardParameters(parameters).coordinationPhone).toBe('01632 960001');
    expect(parseBoardParameters(boardParameters(BOARD_A)).coordinationPhone).toBeNull();
  });

  it('keeps no number that is not a phone number: text, markup or a link is dropped, never shown', () => {
    for (const value of ['call me', '<b>999</b>', 'javascript:alert(1)', 'tel:01632 960001']) {
      const parameters = boardParameters(BOARD_A);
      parameters.parameter?.push({ name: 'coordinationPhone', valueString: value });
      expect(parseBoardParameters(parameters).coordinationPhone).toBeNull();
    }
  });

  it('ignores a part or a top-level parameter it does not know', () => {
    const parameters = boardParameters(BOARD_B);
    parameters.parameter?.[0].part?.push({ name: 'somethingNew', valueString: 'x' });
    parameters.parameter?.push({ name: 'alsoNew', valueString: 'y' });

    expect(parseBoardParameters(parameters).entries).toEqual(BOARD_B.entries);
  });

  it('fails closed on a status it does not know, instead of showing it as something else', () => {
    const parameters = boardParameters(BOARD_B);
    const status = parameters.parameter?.[0].part?.find((p) => p.name === 'status');
    if (status) status.valueCode = 'busy';

    expect(() => parseBoardParameters(parameters)).toThrow(BoardParseError);
  });

  it.each(['serviceId', 'name', 'category', 'status', 'established', 'pending', 'unitLabel'])(
    'fails closed when the required part %s is missing',
    (name) => {
      expect(() => parseBoardParameters(without(boardParameters(BOARD_B), 0, name))).toThrow(BoardParseError);
    },
  );

  it('fails closed when generatedAt is missing or pressure is missing', () => {
    const noClock = boardParameters(BOARD_B);
    noClock.parameter = noClock.parameter?.filter((p) => p.name !== 'generatedAt');
    expect(() => parseBoardParameters(noClock)).toThrow(BoardParseError);

    const noPressure = boardParameters(BOARD_B);
    noPressure.parameter = noPressure.parameter?.filter((p) => p.name !== 'pressure');
    expect(() => parseBoardParameters(noPressure)).toThrow(BoardParseError);
  });

  it('fails closed on a part of the wrong type', () => {
    const parameters = boardParameters(BOARD_B);
    const established = parameters.parameter?.[0].part?.find((p) => p.name === 'established');
    if (established) {
      delete established.valueInteger;
      established.valueString = '8';
    }

    expect(() => parseBoardParameters(parameters)).toThrow(BoardParseError);
  });

  // The integer reader's two guards (W05 verifier note, closed here): a count below
  // zero, and a count that is not a whole number, must never reach a tile.
  function withCount(partName: string, value: number): Parameters {
    const parameters = boardParameters(BOARD_B);
    const target = parameters.parameter?.[0].part?.find((p) => p.name === partName);
    if (!target) throw new Error(`the fixture has no ${partName} part`);
    target.valueInteger = value;
    return parameters;
  }

  it.each(['effectiveAvailable', 'overBy', 'used', 'established', 'pending'])(
    'fails closed on a negative %s, never showing a count such as -3',
    (name) => {
      const parameters = boardParameters(BOARD_B);
      const part = parameters.parameter?.[0].part;
      if (!part?.some((p) => p.name === name)) part?.push({ name, valueInteger: 1 });
      expect(() => parseBoardParameters(withCountOn(parameters, name, -3))).toThrow(BoardParseError);
      expect(() => parseBoardParameters(withCountOn(parameters, name, -1))).toThrow(BoardParseError);
    },
  );

  it('keeps zero, the lowest count it accepts', () => {
    expect(parseBoardParameters(withCount('established', 0)).entries[0].established).toBe(0);
  });

  it.each(['effectiveAvailable', 'used', 'established', 'pending'])(
    'fails closed on a fractional %s, never rounding it',
    (name) => {
      const parameters = boardParameters(BOARD_B);
      const part = parameters.parameter?.[0].part;
      if (!part?.some((p) => p.name === name)) part?.push({ name, valueInteger: 1 });
      expect(() => parseBoardParameters(withCountOn(parameters, name, 2.5))).toThrow(BoardParseError);
      expect(() => parseBoardParameters(withCountOn(parameters, name, 0.1))).toThrow(BoardParseError);
    },
  );

  it('fails closed on a count too large to be exact, and on one that is not a number', () => {
    for (const bad of [Number.MAX_SAFE_INTEGER + 2, Number.POSITIVE_INFINITY, Number.NaN]) {
      expect(() => parseBoardParameters(withCount('established', bad))).toThrow(BoardParseError);
    }
  });

  it('fails closed on a part that appears twice, in an entry or at the top level', () => {
    const twiceInEntry = boardParameters(BOARD_B);
    twiceInEntry.parameter?.[0].part?.push({ name: 'established', valueInteger: 99 });
    expect(() => parseBoardParameters(twiceInEntry)).toThrow(BoardParseError);

    const twiceAtTop = boardParameters(BOARD_B);
    twiceAtTop.parameter?.push({ name: 'generatedAt', valueDateTime: '2026-10-23T13:30:00Z' });
    expect(() => parseBoardParameters(twiceAtTop)).toThrow(BoardParseError);
  });

  it('fails closed on something that is not a Parameters resource', () => {
    expect(() =>
      parseBoardParameters({ resourceType: 'OperationOutcome' } as unknown as Parameters),
    ).toThrow(BoardParseError);
    expect(() => parseBoardParameters(null as unknown as Parameters)).toThrow(BoardParseError);
  });

  it('gives an empty board, not an error, when there are no services', () => {
    const parsed = parseBoardParameters(boardParameters({ ...BOARD_A, entries: [] }));
    expect(parsed.entries).toEqual([]);
    expect(parsed.generatedAt).toBe(GENERATED_AT);
  });

  it('does not put a time in an entry that the back end left out', () => {
    expect(part(boardParameters(BOARD_A), 0).some((p) => p.name === 'wasDueAt')).toBe(false);
    expect(parseBoardParameters(boardParameters(BOARD_A)).entries[0].wasDueAt).toBeNull();
  });
});

describe('parseBoardParameters: the variant boards (W07)', () => {
  it.each([
    ['BoardSurge', BOARD_SURGE],
    ['BoardQuiet', BOARD_QUIET],
  ])('reads the %s sample back exactly, pending, over-by and out-of-hours entries included', (_name, board) => {
    expect(parseBoardParameters(boardParameters(board))).toEqual(board);
  });
});

describe('parseBoardParameters: a foreign organisation or tenant part in the payload (W07, DEC-169 item 8)', () => {
  function withEntryPart(parameters: Parameters, added: ParametersParameter): Parameters {
    const copy = structuredClone(parameters);
    copy.parameter?.find((p) => p.name === 'entry')?.part?.push(added);
    return copy;
  }

  function failure(parameters: Parameters): Error {
    try {
      parseBoardParameters(parameters);
    } catch (error) {
      return error as Error;
    }
    throw new Error('the board was accepted');
  }

  it('refuses a board whose entry names an organisation other than the board’s own', () => {
    const error = failure(withForeignOrganisation(boardParameters(BOARD_A)));

    expect(error).toBeInstanceOf(BoardParseError);
  });

  it('says nothing of the other organisation in the error: the part name only', () => {
    const error = failure(withForeignOrganisation(boardParameters(BOARD_A), 'Secret Neighbour Trust'));

    expect(error.message).not.toContain('Secret Neighbour Trust');
    expect(error.message).not.toContain(ORGANISATION_B);
    expect(error.message).toContain('organisation');
  });

  it('accepts an entry that names the board’s own organisation', () => {
    const parameters = withEntryPart(boardParameters(BOARD_A), { name: 'organisation', valueString: ORGANISATION_A });

    expect(parseBoardParameters(parameters)).toEqual(BOARD_A);
  });

  it('refuses an entry that names an organisation when the board names none, because it cannot tell whose it is', () => {
    const parameters = boardParameters({ ...BOARD_A, organisation: null });

    expect(() => parseBoardParameters(withEntryPart(parameters, { name: 'organisation', valueString: ORGANISATION_A }))).toThrow(
      BoardParseError,
    );
  });

  it.each(['tenantId', 'sourceTenantId'])('refuses an entry that carries a %s: a tenant board never has one', (name) => {
    const parameters = withEntryPart(boardParameters(BOARD_A), { name, valueString: 'tenant-b' });
    const error = failure(parameters);

    expect(error).toBeInstanceOf(BoardParseError);
    expect(error.message).not.toContain('tenant-b');
  });

  it('refuses the foreign entry wherever it is in the board, not only the first', () => {
    const parameters = boardParameters(BOARD_A);
    const last = parameters.parameter?.filter((p) => p.name === 'entry').at(-1);
    last?.part?.push({ name: 'organisation', valueString: ORGANISATION_B });

    expect(() => parseBoardParameters(parameters)).toThrow(BoardParseError);
  });

  it('still ignores a part it does not know, as before', () => {
    const parameters = withEntryPart(boardParameters(BOARD_A), { name: 'somethingNew', valueString: 'x' });

    expect(parseBoardParameters(parameters)).toEqual(BOARD_A);
  });
});
