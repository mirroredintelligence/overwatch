// Which board a wall screen shows (TEN-072, docs/design/network-ui.md section 6): its own organisation's
// or a network's, read from the back end's `GET /screens/me/board-scope` (W9B). The screen's version
// changes whenever its administrator changes the board, and `fallback` says it is set to a network that is
// no longer open to it, so it shows its own board with a notice. The name of the network is the only thing
// of a network that reaches the screen. Nothing here is an identifier of a tenant or a network.

export type WallScope = {
  boardScope: 'tenant' | 'network';
  scopeVersion: number;
  /** The screen is set to a network that is no longer open to it: it shows its own board and says so. */
  fallback: boolean;
  /** The network's name, only when the screen shows a network now. */
  networkName: string | null;
};

/** What a screen that has not been told otherwise shows: its own organisation's board. */
export const OWN_SCOPE: WallScope = { boardScope: 'tenant', scopeVersion: 0, fallback: false, networkName: null };

const NAME_MAX = 200;

export class WallScopeError extends Error {
  constructor() {
    super('The screen’s board setting is not in the expected shape.');
    this.name = 'WallScopeError';
  }
}

/** Reads the back end's answer, and the BFF's, which has the same fields. Fails closed; keeps only what it knows. */
export function parseWallScope(value: unknown): WallScope {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new WallScopeError();
  const { boardScope, fallback, scopeVersion, networkName } = value as Record<string, unknown>;
  if (boardScope !== 'tenant' && boardScope !== 'network') throw new WallScopeError();
  if (typeof fallback !== 'boolean') throw new WallScopeError();
  if (typeof scopeVersion !== 'number' || !Number.isInteger(scopeVersion) || scopeVersion < 0) throw new WallScopeError();
  if (networkName !== undefined && networkName !== null && (typeof networkName !== 'string' || networkName.length > NAME_MAX)) throw new WallScopeError();
  if (boardScope === 'network' && (typeof networkName !== 'string' || networkName === '' || fallback)) throw new WallScopeError();
  return { boardScope, scopeVersion, fallback, networkName: boardScope === 'network' ? (networkName as string) : null };
}

/**
 * What the figures held belong to. A figure is only ever shown as last known under the key it was read
 * under: when the key changes (the administrator chose another board, the version moved, or the screen
 * fell back) the figures of the old key are dropped, never carried over.
 */
export function scopeKey(scope: WallScope): string {
  return JSON.stringify([scope.boardScope, scope.scopeVersion, scope.fallback, scope.networkName]);
}
