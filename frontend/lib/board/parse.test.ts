import { describe, expect, it } from 'vitest';
import type { Parameters, ParametersParameter } from '@/lib/fhir/types';
import { BOARD_A, BOARD_B, boardParameters, entry, entryParameter, GENERATED_AT } from '@/test/fixtures/board';
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
