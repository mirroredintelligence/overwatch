// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SecretConfigurationError, SecretNotFoundError } from '@/lib/secrets/errors';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { server } from '@/test/msw/server';

// The edge-origin secret comes from the vault on the pilot (DEC-1303, DEC-1304). The vault is replaced
// here; the secret module has its own tests.

const secrets = vi.hoisted(() => ({ read: vi.fn<(name: string) => Promise<string>>(), vault: true }));

vi.mock('@/lib/secrets', async (original) => ({
  ...(await original<typeof import('@/lib/secrets')>()),
  getSecret: (name: string) => secrets.read(name),
  vaultConfigured: () => secrets.vault,
}));

import { BackendCallError, callBackend } from './hostCall';

const PING = `${BACKEND_ROOT}/public/ping`;
const EDGE = 'CANARY-edge-origin-from-the-vault-0123456789';

function listen() {
  const seen: { host: string | null; forwarded: string | null; auth: string | null }[] = [];
  server.use(http.get(PING, ({ request }) => {
    seen.push({ host: request.headers.get('host'), forwarded: request.headers.get('x-forwarded-host'), auth: request.headers.get('x-edge-auth') });
    return HttpResponse.json({ ok: true });
  }));
  return seen;
}

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  secrets.vault = true;
  secrets.read.mockReset();
  secrets.read.mockResolvedValue(EDGE);
});

describe('with the vault', () => {
  it('sends the tenant host in X-Forwarded-Host with the edge-origin secret, and reads that secret only', async () => {
    const seen = listen();
    await callBackend({ method: 'GET', path: '/public/ping', host: 'Tenant-A.example.test' });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ forwarded: 'tenant-a.example.test', auth: EDGE });
    expect(seen[0]?.host).not.toBe('tenant-a.example.test');
    expect(secrets.read.mock.calls).toEqual([['edge-origin']]);
  });

  it.each([
    ['missing', () => new SecretNotFoundError('edge-origin')],
    ['unreadable', () => new SecretConfigurationError('The secret edge-origin could not be read.')],
  ])('is a fault when the secret is %s: nothing is sent, and the call does not fall back to Host', async (_kind, failure) => {
    secrets.read.mockRejectedValue(failure());
    const seen = listen();
    const error = await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(BackendCallError);
    expect(seen).toEqual([]);
    expect((error as Error).message).toContain('edge-origin');
  });

  it('does not read the secret for a host that is refused', async () => {
    await expect(callBackend({ method: 'GET', path: '/public/ping', host: 'a b' })).rejects.toBeInstanceOf(BackendCallError);
    expect(secrets.read).not.toHaveBeenCalled();
  });

  it('is a fault, not an edge header, when the secret is not a header-safe value', async () => {
    secrets.read.mockResolvedValue('line one\r\nX-Injected: yes');
    const seen = listen();
    await expect(callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' })).rejects.toThrow(/edge-origin/);
    expect(seen).toEqual([]);
  });
});

describe('without the vault (local runs and tests)', () => {
  beforeEach(() => {
    secrets.vault = false;
  });

  it('uses the Host header when there is no edge secret', async () => {
    secrets.read.mockRejectedValue(new SecretNotFoundError('edge-origin'));
    const seen = listen();
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    expect(seen[0]).toMatchObject({ host: 'a.test', forwarded: null, auth: null });
  });

  it('uses the edge headers when the environment gives a secret', async () => {
    const seen = listen();
    await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    expect(seen[0]).toMatchObject({ forwarded: 'a.test', auth: EDGE });
  });

  it('is still a fault when the secret cannot be read for another reason', async () => {
    secrets.read.mockRejectedValue(new SecretConfigurationError('configuration'));
    await expect(callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' })).rejects.toBeInstanceOf(SecretConfigurationError);
  });
});
