import { beforeEach, describe, expect, it } from 'vitest';
import { deviceExchange, standInToken } from '@/test/fixtures/exchange';
import { SIGN_IN_HOST } from '@/test/oidc/constants';
import { PairingStandIn, STAND_IN_NETWORK } from './pairing';

// The stand-in's lead administration answers the shapes of routes_screens.py: GET /screens is
// `{scope, asOf, screens: [...]}`, POST /screens/{id}/revoke is `{deviceId, status: 'revoked', revokedAt}`.

const lead = `Bearer ${standInToken({ sub: 'stf-1', role: 'lead', aud: 'overwatch-api', exp: Math.floor(Date.now() / 1000) + 3600 })}`;
const advisor = `Bearer ${standInToken({ sub: 'stf-2', role: 'advisor', aud: 'overwatch-api', exp: Math.floor(Date.now() / 1000) + 3600 })}`;
const stand = new PairingStandIn();

function pair(): { deviceId: string; deviceToken: string } {
  const started = stand.start(SIGN_IN_HOST).body as { pairingId: string; code: string; screenSecret: string };
  const connected = stand.connect(SIGN_IN_HOST, lead, 'k-pair', { code: started.code, name: 'Ward 4', location: 'Level 2' }).body as { deviceId: string };
  const claimed = stand.claim(SIGN_IN_HOST, started.pairingId, started.screenSecret).body as { deviceToken: string };
  return { deviceId: connected.deviceId, deviceToken: claimed.deviceToken };
}

beforeEach(() => stand.reset());

describe('the stand-in’s list and revoke', () => {
  it('lists a screen waiting, then online once it has collected its token', () => {
    const started = stand.start(SIGN_IN_HOST).body as { pairingId: string; code: string; screenSecret: string };
    stand.connect(SIGN_IN_HOST, lead, 'k', { code: started.code, name: 'Ward 4' });
    const waiting = (stand.list(SIGN_IN_HOST, lead).body as { screens: { state: string }[] }).screens;
    expect(waiting.map((s) => s.state)).toEqual(['waiting']);
    stand.claim(SIGN_IN_HOST, started.pairingId, started.screenSecret);
    const online = stand.list(SIGN_IN_HOST, lead).body as { scope: string; screens: { state: string; location: string | null }[] };
    expect(online.scope).toBe('tenant');
    expect(online.screens.map((s) => s.state)).toEqual(['online']);
  });

  it('answers the one 404 to a role that is not a lead, and lists nothing for another host', () => {
    pair();
    expect(stand.list(SIGN_IN_HOST, advisor).status).toBe(404);
    expect((stand.list('another.example.test', lead).body as { screens: unknown[] }).screens).toEqual([]);
  });

  it('revokes a screen: the list says so, and its device token gets no new wall token', () => {
    const { deviceId, deviceToken } = pair();
    expect(deviceExchange(SIGN_IN_HOST, `Bearer ${deviceToken}`, {}).status).toBe(200);
    const revoked = stand.revoke(SIGN_IN_HOST, lead, 'k-rev', deviceId);
    expect(revoked.status).toBe(200);
    expect(revoked.body).toMatchObject({ deviceId, status: 'revoked' });
    expect(deviceExchange(SIGN_IN_HOST, `Bearer ${deviceToken}`, {}).status).toBe(404);
    expect((stand.list(SIGN_IN_HOST, lead).body as { screens: { state: string }[] }).screens.map((s) => s.state)).toEqual(['revoked']);
  });

  it('needs a key, refuses a non-lead, and does not know another host’s screen', () => {
    const { deviceId } = pair();
    expect(stand.revoke(SIGN_IN_HOST, lead, null, deviceId).status).toBe(400);
    expect(stand.revoke(SIGN_IN_HOST, advisor, 'k', deviceId).status).toBe(404);
    expect(stand.revoke('another.example.test', lead, 'k', deviceId).status).toBe(404);
    expect(stand.revoke(SIGN_IN_HOST, lead, 'k', 'nowhere').status).toBe(404);
  });
});


describe('the stand-in’s board choice and preview (TEN-072)', () => {
  it('lists the network the tenant may choose, and a screen on its own board with its version', () => {
    pair();
    const body = stand.list(SIGN_IN_HOST, lead).body as { networks: unknown[]; screens: { boardScope: string; scopeVersion: number }[] };
    expect(body.networks).toEqual([STAND_IN_NETWORK]);
    expect(body.screens[0]).toMatchObject({ boardScope: 'tenant', scopeVersion: 1 });
  });

  it('sets a screen to the network with the right version, moves the version, and says what the screen shows', () => {
    const { deviceId } = pair();
    const changed = stand.setBoard(SIGN_IN_HOST, lead, 'k-b', 'W/"1"', deviceId, { boardScope: 'network', networkId: STAND_IN_NETWORK.id });
    expect(changed.status).toBe(200);
    expect(changed.body).toMatchObject({ boardScope: 'network', networkName: STAND_IN_NETWORK.name, scopeVersion: 2 });
    expect(stand.ownBoardScope(deviceId).body).toMatchObject({ boardScope: 'network', scopeVersion: 2, networkName: STAND_IN_NETWORK.name });
    expect(stand.setBoard(SIGN_IN_HOST, lead, 'k-c', 'W/"1"', deviceId, { boardScope: 'tenant' }).status).toBe(412);
  });

  it('refuses a non-lead, no key, no If-Match, a network it does not know and another host’s screen', () => {
    const { deviceId } = pair();
    const body = { boardScope: 'network', networkId: STAND_IN_NETWORK.id };
    expect(stand.setBoard(SIGN_IN_HOST, advisor, 'k', 'W/"1"', deviceId, body).status).toBe(404);
    expect(stand.setBoard(SIGN_IN_HOST, lead, null, 'W/"1"', deviceId, body).status).toBe(400);
    expect(stand.setBoard(SIGN_IN_HOST, lead, 'k', null, deviceId, body).status).toBe(428);
    expect(stand.setBoard(SIGN_IN_HOST, lead, 'k', 'W/"1"', deviceId, { boardScope: 'network', networkId: 'net-other' }).status).toBe(404);
    expect(stand.setBoard('another.example.test', lead, 'k', 'W/"1"', deviceId, body).status).toBe(404);
  });

  it('previews a live code with when it first asked, and refuses a code that is not live', () => {
    const started = stand.start(SIGN_IN_HOST).body as { code: string };
    const seen = stand.preview(SIGN_IN_HOST, lead, { code: started.code });
    expect(seen.status).toBe(200);
    expect(seen.body).toMatchObject({ deviceClass: 'wall-display' });
    expect(stand.preview(SIGN_IN_HOST, lead, { code: '000000' }).status).toBe(404);
    expect(stand.preview(SIGN_IN_HOST, advisor, { code: started.code }).status).toBe(404);
    expect(stand.preview('another.example.test', lead, { code: started.code }).status).toBe(404);
  });
});
