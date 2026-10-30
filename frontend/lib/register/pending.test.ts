// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { PENDING_COOKIE, readPending, sealPending } from './pending';

// The sealed record between a code request and its check: the device id and the invitation token
// the browser never sees. It is sealed with the session key and lives 15 minutes.

const DEVICE = 'Dev1ceIdSampleValue_ab';
const INVITE = 'InviteTokenSampleValue1';
const URL_ = 'https://tenant-a.example.test/api/bff/identity/code/verify';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
});

describe('sealPending and readPending', () => {
  it('round-trips the device id and the invitation', async () => {
    const sealed = await sealPending({ deviceId: DEVICE, inviteToken: INVITE });
    const back = await readPending(requestWithCookies(URL_, { [PENDING_COOKIE]: sealed }));
    expect(back).toEqual({ deviceId: DEVICE, inviteToken: INVITE });
  });

  it('keeps neither value in the clear', async () => {
    const sealed = await sealPending({ deviceId: DEVICE, inviteToken: INVITE });
    expect(sealed).not.toContain(DEVICE);
    expect(sealed).not.toContain(INVITE);
  });

  it('is null once fifteen minutes have passed', async () => {
    const start = new Date('2026-10-30T10:00:00Z');
    const sealed = await sealPending({ deviceId: DEVICE, inviteToken: INVITE }, start);
    const later = new Date(start.getTime() + 15 * 60_000 + 1000);
    expect(await readPending(requestWithCookies(URL_, { [PENDING_COOKIE]: sealed }), later)).toBeNull();
  });

  it('is null when the cookie is missing, altered, or is a session cookie', async () => {
    const sealed = await sealPending({ deviceId: DEVICE, inviteToken: INVITE });
    expect(await readPending(requestWithCookies(URL_, {}))).toBeNull();
    expect(await readPending(requestWithCookies(URL_, { [PENDING_COOKIE]: `${sealed}x` }))).toBeNull();
    expect(await readPending(requestWithCookies(URL_, { [SESSION_COOKIE]: sealed }))).toBeNull();
  });
});
