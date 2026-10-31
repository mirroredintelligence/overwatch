// The lead's wall screen list and revoke as the back end answers them (GET /screens and POST
// /screens/{id}/revoke, routes_screens.py), checked before a page or a BFF answer uses them (W9I,
// TEN-072). A shape that is not the one expected is an error, never an empty list. Only the fields a
// page shows are kept: a token, a hash or a secret that a back end sent by mistake is dropped here, so
// it cannot reach the browser.

export type ScreenStatus = 'online' | 'offline' | 'waiting' | 'never-connected' | 'revoked';
export type ScreenBoard = 'tenant' | 'network';

export type ScreenRow = {
  deviceId: string;
  name: string;
  location: string | null;
  /** What the lead is told (online, offline, ...). The back end's `status` is the device's own and is not read. */
  state: ScreenStatus;
  boardScope: ScreenBoard;
  pairedAt: string | null;
  lastSeenAt: string | null;
  revokedAt: string | null;
};

/** `scope` is `tenant` for the lead's own organisation; the network list (TEN-072, later) is another scope. */
export type ScreenList = { scope: 'tenant'; asOf: string; screens: ScreenRow[] };
export type Revoked = { deviceId: string; status: 'revoked'; revokedAt: string };

export const STATUS_WORDS: Record<ScreenStatus, string> = {
  online: 'Online',
  offline: 'Offline',
  waiting: 'Waiting to connect',
  'never-connected': 'Never connected',
  revoked: 'Disconnected',
};

const STATUSES = Object.keys(STATUS_WORDS) as ScreenStatus[];
const DEVICE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const NAME_MAX = 120;

type Json = Record<string, unknown>;

export class ScreenAnswerError extends Error {
  constructor() {
    super('The answer about the screens was not the one expected.');
    this.name = 'ScreenAnswerError';
  }
}

const bad = () => new ScreenAnswerError();
const isObject = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value);

function instant(value: unknown): string {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) throw bad();
  return value;
}

function optionalInstant(value: unknown): string | null {
  return value === null || value === undefined ? null : instant(value);
}

function row(value: unknown): ScreenRow {
  if (!isObject(value)) throw bad();
  const { deviceId, name, location, state, boardScope } = value;
  if (typeof deviceId !== 'string' || !DEVICE_ID.test(deviceId)) throw bad();
  if (typeof name !== 'string' || name.length === 0 || name.length > NAME_MAX) throw bad();
  if (location !== null && location !== undefined && (typeof location !== 'string' || location.length > NAME_MAX)) throw bad();
  if (typeof state !== 'string' || !STATUSES.includes(state as ScreenStatus)) throw bad();
  if (boardScope !== 'tenant' && boardScope !== 'network') throw bad();
  return {
    deviceId,
    name,
    location: typeof location === 'string' ? location : null,
    state: state as ScreenStatus,
    boardScope,
    pairedAt: optionalInstant(value.pairedAt),
    lastSeenAt: optionalInstant(value.lastSeenAt),
    revokedAt: optionalInstant(value.revokedAt),
  };
}

export function screenListFrom(value: unknown): ScreenList {
  if (!isObject(value) || value.scope !== 'tenant' || !Array.isArray(value.screens)) throw bad();
  return { scope: 'tenant', asOf: instant(value.asOf), screens: value.screens.map(row) };
}

export function revokedFrom(value: unknown): Revoked {
  if (!isObject(value) || value.status !== 'revoked') throw bad();
  const { deviceId } = value;
  if (typeof deviceId !== 'string' || !DEVICE_ID.test(deviceId)) throw bad();
  return { deviceId, status: 'revoked', revokedAt: instant(value.revokedAt) };
}
