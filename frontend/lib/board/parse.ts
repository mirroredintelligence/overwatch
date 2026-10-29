import type { Parameters, ParametersParameter } from '@/lib/fhir/types';
import type { Board, BoardEntry, BoardStatus } from './types';

// Reads the back end's `$board` Parameters into a Board. It fails closed: a
// status it does not know, a missing required part, a part of the wrong type or
// a repeated part is an error, never a guess, because a wrong figure on a wall
// board is worse than no figure. Parts it does not know are ignored, so the back
// end can add one without breaking the wall.

export class BoardParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BoardParseError';
  }
}

// A Record, so adding a status to BoardStatus fails the type check until it is added here.
const STATUS_SET: Record<BoardStatus, true> = {
  accepting: true,
  limited: true,
  'not-accepting': true,
  'over-capacity': true,
  'not-updated': true,
  'out-of-hours': true,
};

export function isStatus(value: string): value is BoardStatus {
  return Object.hasOwn(STATUS_SET, value);
}

function fail(what: string): never {
  // Names the part only. Never a value from the body.
  throw new BoardParseError(`The board is not in the expected shape (${what}).`);
}

/** Looks up named parts, refusing a part that appears twice. */
function index(parts: ParametersParameter[], known: readonly string[]): Map<string, ParametersParameter> {
  const found = new Map<string, ParametersParameter>();
  for (const part of parts) {
    if (!known.includes(part.name)) continue;
    if (found.has(part.name)) fail(`${part.name} is repeated`);
    found.set(part.name, part);
  }
  return found;
}

type Reader<T> = (part: ParametersParameter) => T | undefined;

const string: Reader<string> = (p) => (typeof p.valueString === 'string' ? p.valueString : undefined);
const code: Reader<string> = (p) => (typeof p.valueCode === 'string' ? p.valueCode : undefined);
const boolean: Reader<boolean> = (p) => (typeof p.valueBoolean === 'boolean' ? p.valueBoolean : undefined);
const integer: Reader<number> = (p) =>
  typeof p.valueInteger === 'number' && Number.isSafeInteger(p.valueInteger) && p.valueInteger >= 0
    ? p.valueInteger
    : undefined;
const instant: Reader<string> = (p) =>
  typeof p.valueDateTime === 'string' && !Number.isNaN(Date.parse(p.valueDateTime))
    ? p.valueDateTime
    : undefined;

function required<T>(parts: Map<string, ParametersParameter>, name: string, read: Reader<T>): T {
  const part = parts.get(name);
  const value = part === undefined ? undefined : read(part);
  if (value === undefined) fail(`${name} is missing or of the wrong type`);
  return value;
}

function optional<T>(parts: Map<string, ParametersParameter>, name: string, read: Reader<T>): T | null {
  const part = parts.get(name);
  if (part === undefined) return null;
  const value = read(part);
  if (value === undefined) fail(`${name} is of the wrong type`);
  return value;
}

const ENTRY_PARTS = [
  'serviceId',
  'name',
  'category',
  'status',
  'effectiveAvailable',
  'overBy',
  'used',
  'established',
  'pending',
  'unitLabel',
  'comment',
  'reportedAt',
  'nextDueAt',
  'wasDueAt',
] as const;

function parseEntry(parameter: ParametersParameter): BoardEntry {
  const parts = index(parameter.part ?? [], ENTRY_PARTS);
  const status = required(parts, 'status', code);
  if (!isStatus(status)) fail('status is not one the board knows');
  return {
    serviceId: required(parts, 'serviceId', string),
    name: required(parts, 'name', string),
    category: required(parts, 'category', code),
    status,
    effectiveAvailable: optional(parts, 'effectiveAvailable', integer),
    overBy: optional(parts, 'overBy', integer),
    used: optional(parts, 'used', integer),
    established: required(parts, 'established', integer),
    pending: required(parts, 'pending', integer),
    unitLabel: required(parts, 'unitLabel', string),
    comment: optional(parts, 'comment', string),
    reportedAt: optional(parts, 'reportedAt', instant),
    nextDueAt: optional(parts, 'nextDueAt', instant),
    wasDueAt: optional(parts, 'wasDueAt', instant),
  };
}

const TOP_LEVEL = ['pressure', 'allLimitedOrWorse', 'generatedAt', 'organisation'] as const;

export function parseBoardParameters(parameters: Parameters): Board {
  if (typeof parameters !== 'object' || parameters === null || parameters.resourceType !== 'Parameters') {
    fail('not a Parameters resource');
  }
  const all = parameters.parameter ?? [];
  const top = index(all, TOP_LEVEL);
  return {
    entries: all.filter((p) => p.name === 'entry').map(parseEntry),
    pressure: required(top, 'pressure', code),
    allLimitedOrWorse: required(top, 'allLimitedOrWorse', boolean),
    generatedAt: required(top, 'generatedAt', instant),
    organisation: optional(top, 'organisation', string),
  };
}
