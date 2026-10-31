import { describe, expect, it } from 'vitest';
import { revokedFrom, screenListFrom, STATUS_WORDS } from './admin';

// The lead's list of wall screens as the back end gives it (GET /screens, routes_screens.py), checked
// before a page shows it. A shape that is not the one expected is an error, never an empty list.

const ROW = {
  deviceId: 's-1',
  name: 'Ward 4 corridor',
  location: 'Level 2',
  state: 'online',
  boardScope: 'tenant',
  pairedAt: '2026-10-27T10:00:00Z',
  lastSeenAt: '2026-10-30T09:59:20Z',
  revokedAt: null,
};
const BODY = { scope: 'tenant', asOf: '2026-10-30T10:00:00Z', screens: [ROW] };

describe('screenListFrom', () => {
  it('reads the list the back end gives', () => {
    expect(screenListFrom(BODY)).toEqual(BODY);
  });

  it('keeps a screen with no place and one never seen', () => {
    const waiting = { ...ROW, location: null, state: 'waiting', lastSeenAt: null };
    expect(screenListFrom({ ...BODY, screens: [waiting] }).screens).toEqual([waiting]);
  });

  it('reads an empty list as an empty list', () => {
    expect(screenListFrom({ ...BODY, screens: [] }).screens).toEqual([]);
  });

  it.each([
    ['not an object', 'x'],
    ['no screens', { scope: 'tenant', asOf: BODY.asOf }],
    ['screens not a list', { ...BODY, screens: {} }],
    ['an unknown scope', { ...BODY, scope: 'galaxy' }],
    ['no time', { scope: 'tenant', screens: [ROW] }],
    ['a time that is not a time', { ...BODY, asOf: 'yesterday' }],
    ['a row with no id', { ...BODY, screens: [{ ...ROW, deviceId: undefined }] }],
    ['a row with an id that is not an id', { ...BODY, screens: [{ ...ROW, deviceId: '../x' }] }],
    ['a row with no name', { ...BODY, screens: [{ ...ROW, name: '' }] }],
    ['a row with an unknown state', { ...BODY, screens: [{ ...ROW, state: 'happy' }] }],
    ['a row with an unknown board', { ...BODY, screens: [{ ...ROW, boardScope: 'moon' }] }],
    ['a row with a paired time that is not a time', { ...BODY, screens: [{ ...ROW, pairedAt: 'x' }] }],
    ['a row with a place that is a number', { ...BODY, screens: [{ ...ROW, location: 4 }] }],
  ])('refuses %s', (_name, body) => {
    expect(() => screenListFrom(body)).toThrow();
  });

  it('drops a field it does not know, so a token or hash a back end sent by mistake never reaches a page', () => {
    const leaky = { ...ROW, tokenHash: 'a'.repeat(64), deviceToken: 'AbCdEf' };
    const out = screenListFrom({ ...BODY, screens: [leaky] });
    expect(JSON.stringify(out)).not.toContain('tokenHash');
    expect(JSON.stringify(out)).not.toContain('deviceToken');
  });
});

describe('revokedFrom', () => {
  it('reads the answer to a revoke', () => {
    const answer = { deviceId: 's-1', status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' };
    expect(revokedFrom(answer)).toEqual(answer);
  });

  it.each([
    ['another status', { deviceId: 's-1', status: 'online', revokedAt: '2026-10-30T10:00:00Z' }],
    ['no id', { status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' }],
    ['no time', { deviceId: 's-1', status: 'revoked' }],
    ['not an object', null],
  ])('refuses %s', (_name, body) => {
    expect(() => revokedFrom(body)).toThrow();
  });
});

describe('the words for a status', () => {
  it('has a plain word for each, none of them a colour', () => {
    expect(STATUS_WORDS).toEqual({
      online: 'Online',
      offline: 'Offline',
      waiting: 'Waiting to connect',
      'never-connected': 'Never connected',
      revoked: 'Disconnected',
    });
  });
});
