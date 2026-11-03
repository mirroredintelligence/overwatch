// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sealChoice, unsealChoice, CHOICE_SECONDS } from './flow';
import type { StaffTenant } from './exchange';
import { TEST_SESSION_SECRET } from '@/test/cookies';

// The tenant picker's sealed list (DEC-1327): sealed with a purpose of its own, ten minutes long, and
// read back only if it is ours, unexpired and well formed. A node environment: the sealing needs Node's
// byte arrays.

const LIST: StaffTenant[] = [
  { id: 'fortrus-limited', name: 'Fortrus Limited', roles: ['lead', 'advisor'] },
  { id: 'trust-b', name: 'Trust B', roles: ['advisor'] },
];

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
});

describe('the sealed tenant choices', () => {
  it('reads back the list it sealed, within its life', async () => {
    const now = new Date();
    const sealed = await sealChoice(LIST, now);
    expect(await unsealChoice(sealed, now)).toEqual(LIST);
  });

  it('gives nothing once its ten minutes have passed', async () => {
    const sealedAt = new Date('2026-11-03T10:00:00Z');
    const sealed = await sealChoice(LIST, sealedAt);
    const later = new Date(sealedAt.getTime() + (CHOICE_SECONDS + 1) * 1000);
    expect(await unsealChoice(sealed, later)).toBeNull();
  });

  it('gives nothing for a value that is not ours, or is changed', async () => {
    const now = new Date();
    const sealed = await sealChoice(LIST, now);
    const changed = `${sealed.slice(0, -2)}${sealed.endsWith('A') ? 'B' : 'A'}`;
    expect(await unsealChoice(changed, now)).toBeNull();
    expect(await unsealChoice('not-a-token', now)).toBeNull();
    expect(await unsealChoice('', now)).toBeNull();
  });

  it('gives nothing for a list that names an organisation by a value that is not a tenant id', async () => {
    const now = new Date();
    const bad: StaffTenant[] = [{ id: 'Trust A', name: 'Bad', roles: ['advisor'] }];
    const sealed = await sealChoice(bad, now);
    expect(await unsealChoice(sealed, now)).toBeNull();
  });
});
