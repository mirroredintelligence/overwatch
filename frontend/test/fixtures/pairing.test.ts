import { beforeEach, describe, expect, it } from 'vitest';
import { deviceExchange, standInToken } from '@/test/fixtures/exchange';
import { SIGN_IN_HOST } from '@/test/oidc/constants';
import { PairingStandIn } from './pairing';

// The stand-in's lead administration answers the shapes of routes_screens.py: GET /screens is
// `{scope, asOf, screens: [...]}`, POST /screens/{id}/revoke is `{deviceId, status: 'revoked', revokedAt}`.

const lead = `Bearer ${standInToken({ sub: 'stf-1', role: 'lead', aud: 'diucs-api', exp: Math.floor(Date.now() / 1000) + 3600 })}`;
const advisor = `Bearer ${standInToken({ sub: 'stf-2', role: 'advisor', aud: 'diucs-api', exp: Math.floor(Date.now() / 1000) + 3600 })}`;
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
