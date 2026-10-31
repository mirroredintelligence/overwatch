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
  /** The network this screen is set to, as the server offered it; null on its own board. */
  networkId: string | null;
  networkName: string | null;
  /** False when the screen is set to a network that is no longer open to it: it shows its own board. */
  networkAvailable: boolean;
  /** Sent back as `If-Match` when the board is changed (TEN-067). */
  scopeVersion: number;
  pairedAt: string | null;
  lastSeenAt: string | null;
  revokedAt: string | null;
};

/** A network the organisation may choose for a screen, as the server offered it (never typed). */
export type ChoosableNetwork = { id: string; name: string };

/** `scope` is `tenant`: the list is the lead's own organisation's screens. */
export type ScreenList = { scope: 'tenant'; asOf: string; screens: ScreenRow[]; networks: ChoosableNetwork[] };
export type BoardChanged = Pick<ScreenRow, 'deviceId' | 'boardScope' | 'networkId' | 'networkName' | 'networkAvailable' | 'scopeVersion'>;
export type Revoked = { deviceId: string; status: 'revoked'; revokedAt: string };

export const STATUS_WORDS: Record<ScreenStatus, string> = {
  online: 'Online',
  offline: 'Offline',
  waiting: 'Waiting to be connected',
  'never-connected': 'Never connected',
  revoked: 'Unpaired',
};

const STATUSES = Object.keys(STATUS_WORDS) as ScreenStatus[];
const DEVICE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const NAME_MAX = 120;
// A network id as the back end makes it (`check_network_id`).
const NETWORK_ID = /^net-[a-z0-9][a-z0-9-]{1,26}$/;

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

function networkIdOf(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string' || !NETWORK_ID.test(value)) throw bad();
  return value;
}

/** The board setting of a screen as `GET /screens` and `PUT .../board-scope` answer it. */
function setting(value: Json): Pick<ScreenRow, 'boardScope' | 'networkId' | 'networkName' | 'networkAvailable' | 'scopeVersion'> {
  const { boardScope, networkName, networkAvailable, scopeVersion } = value;
  if (boardScope !== 'tenant' && boardScope !== 'network') throw bad();
  const networkId = networkIdOf(value.networkId);
  if (boardScope === 'network' && networkId === null) throw bad();
  if (networkName !== null && networkName !== undefined && (typeof networkName !== 'string' || networkName.length > NAME_MAX)) throw bad();
  if (typeof scopeVersion !== 'number' || !Number.isInteger(scopeVersion) || scopeVersion < 0) throw bad();
  return {
    boardScope,
    networkId,
    networkName: typeof networkName === 'string' ? networkName : null,
    networkAvailable: networkAvailable !== false,
    scopeVersion,
  };
}

function network(value: unknown): ChoosableNetwork {
  if (!isObject(value)) throw bad();
  const { id, name } = value;
  if (typeof id !== 'string' || !NETWORK_ID.test(id)) throw bad();
  if (typeof name !== 'string' || name.length === 0 || name.length > NAME_MAX) throw bad();
  return { id, name };
}

function row(value: unknown): ScreenRow {
  if (!isObject(value)) throw bad();
  const { deviceId, name, location, state } = value;
  if (typeof deviceId !== 'string' || !DEVICE_ID.test(deviceId)) throw bad();
  if (typeof name !== 'string' || name.length === 0 || name.length > NAME_MAX) throw bad();
  if (location !== null && location !== undefined && (typeof location !== 'string' || location.length > NAME_MAX)) throw bad();
  if (typeof state !== 'string' || !STATUSES.includes(state as ScreenStatus)) throw bad();
  return {
    deviceId,
    name,
    location: typeof location === 'string' ? location : null,
    state: state as ScreenStatus,
    ...setting(value),
    pairedAt: optionalInstant(value.pairedAt),
    lastSeenAt: optionalInstant(value.lastSeenAt),
    revokedAt: optionalInstant(value.revokedAt),
  };
}

export function screenListFrom(value: unknown): ScreenList {
  if (!isObject(value) || value.scope !== 'tenant' || !Array.isArray(value.screens) || !Array.isArray(value.networks)) throw bad();
  return { scope: 'tenant', asOf: instant(value.asOf), screens: value.screens.map(row), networks: value.networks.map(network) };
}

/** The answer to `PUT /screens/{id}/board-scope`: the screen's setting as it is now (with its new version). */
export function boardChangedFrom(value: unknown): BoardChanged {
  if (!isObject(value)) throw bad();
  const { deviceId } = value;
  if (typeof deviceId !== 'string' || !DEVICE_ID.test(deviceId)) throw bad();
  return { deviceId, ...setting(value) };
}

export function revokedFrom(value: unknown): Revoked {
  if (!isObject(value) || value.status !== 'revoked') throw bad();
  const { deviceId } = value;
  if (typeof deviceId !== 'string' || !DEVICE_ID.test(deviceId)) throw bad();
  return { deviceId, status: 'revoked', revokedAt: instant(value.revokedAt) };
}
