import { describe, expect, it } from 'vitest';
import { OWN_SCOPE, parseWallScope, scopeKey } from './scope';

// Which board a wall screen shows (TEN-072, W9B's GET /screens/me/board-scope): its own organisation's or a
// network's, with the screen's version, and a flag when the network is no longer open to it.

describe('parseWallScope', () => {
  it('reads a screen on its own board', () => {
    expect(parseWallScope({ boardScope: 'tenant', fallback: false, scopeVersion: 2 })).toEqual({ boardScope: 'tenant', scopeVersion: 2, fallback: false, networkName: null });
  });

  it('reads a screen on a network, with the network’s name', () => {
    expect(parseWallScope({ boardScope: 'network', fallback: false, scopeVersion: 3, networkName: 'West Dorset system' })).toEqual({
      boardScope: 'network',
      scopeVersion: 3,
      fallback: false,
      networkName: 'West Dorset system',
    });
  });

  it('reads a screen that fell back: its own board, with the flag, and keeps no reason text', () => {
    const scope = parseWallScope({ boardScope: 'tenant', fallback: true, fallbackReason: 'network-unavailable', scopeVersion: 4 });
    expect(scope).toEqual({ boardScope: 'tenant', scopeVersion: 4, fallback: true, networkName: null });
    expect(JSON.stringify(scope)).not.toContain('network-unavailable');
  });

  it('drops a field it does not know', () => {
    const scope = parseWallScope({ boardScope: 'tenant', fallback: false, scopeVersion: 1, tenantId: 'x', networkId: 'net-x' });
    expect(JSON.stringify(scope)).not.toMatch(/tenantId|net-x/);
  });

  it.each([
    ['not an object', 'x'],
    ['an unknown board', { boardScope: 'moon', fallback: false, scopeVersion: 1 }],
    ['no flag', { boardScope: 'tenant', scopeVersion: 1 }],
    ['a version that is not a count', { boardScope: 'tenant', fallback: false, scopeVersion: -1 }],
    ['a network board with no name', { boardScope: 'network', fallback: false, scopeVersion: 1 }],
    ['a network board that is also a fallback', { boardScope: 'network', fallback: true, scopeVersion: 1, networkName: 'x' }],
    ['a name that is not text', { boardScope: 'network', fallback: false, scopeVersion: 1, networkName: 5 }],
  ])('refuses %s', (_name, body) => {
    expect(() => parseWallScope(body)).toThrow();
  });
});

describe('scopeKey', () => {
  it('is the same for the same board and version', () => {
    expect(scopeKey(OWN_SCOPE)).toBe(scopeKey({ ...OWN_SCOPE }));
  });

  it('changes with the board, the version and the fallback flag, so a held figure is never read as another scope’s', () => {
    const base = { boardScope: 'network' as const, scopeVersion: 1, fallback: false, networkName: 'A' };
    const keys = new Set([
      scopeKey(base),
      scopeKey({ ...base, scopeVersion: 2 }),
      scopeKey({ ...base, boardScope: 'tenant', networkName: null }),
      scopeKey({ ...base, boardScope: 'tenant', networkName: null, fallback: true }),
      scopeKey({ ...base, networkName: 'B' }),
    ]);
    expect(keys.size).toBe(5);
  });
});
