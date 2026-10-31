// @vitest-environment node
import { EncryptJWT } from 'jose';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sealSession, sessionSecretKey } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { RECORDED_ANSWER } from '@/test/fixtures/links';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { sealThanks, unsealThanks } from './thanks';

// The thank-you page's detail travels as a sealed value (KI-179): the address holds no link token, and a
// hand-made address cannot make the page say a figure was recorded.

const NOW = new Date('2026-10-23T09:12:30Z');

beforeEach(() => vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET));

describe('the sealed thank-you detail', () => {
  it('reads back what was sealed', async () => {
    const sealed = await sealThanks(RECORDED_ANSWER, NOW);
    expect(await unsealThanks(sealed, NOW)).toEqual(RECORDED_ANSWER);
  });

  it('holds neither a link token nor anything the page does not show', async () => {
    const sealed = await sealThanks(RECORDED_ANSWER, NOW);
    expect(sealed).not.toContain('UCR West');
    expect(sealed).not.toContain('RecordedLinkTokenAbcdef');
  });

  it('is good for ten minutes and no longer', async () => {
    const sealed = await sealThanks(RECORDED_ANSWER, NOW);
    expect(await unsealThanks(sealed, new Date(NOW.getTime() + 9 * 60_000))).not.toBeNull();
    expect(await unsealThanks(sealed, new Date(NOW.getTime() + 11 * 60_000))).toBeNull();
  });

  it.each([
    ['nothing', ''],
    ['text that is not sealed', 'serviceName=UCR+West&value=4'],
    ['a value of the old address', 'serviceName=UCR+West&value=4&unit=x&at=2026-10-23T09%3A12%3A00Z'],
  ])('reads nothing from %s', async (_name, value) => {
    expect(await unsealThanks(value, NOW)).toBeNull();
  });

  it('reads nothing from a value that was tampered with', async () => {
    const sealed = await sealThanks(RECORDED_ANSWER, NOW);
    const tampered = `${sealed.slice(0, -4)}AAAA`;
    expect(await unsealThanks(tampered, NOW)).toBeNull();
  });

  it('reads nothing from a session cookie, which is sealed with the same key', async () => {
    const cookie = await sealSession(sessionFor(TENANTS.A, 'advisor'), NOW);
    expect(await unsealThanks(cookie, NOW)).toBeNull();
  });

  it('is not a session: a sealed thank-you is not accepted where a session is', async () => {
    const { unsealSession } = await import('@/lib/auth/session');
    const sealed = await sealThanks(RECORDED_ANSWER, NOW);
    expect(await unsealSession(sealed, NOW)).toBeNull();
  });

  it('reads nothing from a value sealed for another purpose with the same key and the right claims', async () => {
    const forged = await new EncryptJWT({ ...RECORDED_ANSWER })
      .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
      .setIssuedAt(Math.floor(NOW.getTime() / 1000))
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
      .encrypt(sessionSecretKey());
    expect(await unsealThanks(forged, NOW)).toBeNull();
  });

  it('refuses to seal an answer that is not a whole one', async () => {
    await expect(sealThanks({ ...RECORDED_ANSWER, value: 1000 }, NOW)).rejects.toThrow();
  });
});
