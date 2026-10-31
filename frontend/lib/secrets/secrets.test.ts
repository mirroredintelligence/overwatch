// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createSecrets,
  isSecretName,
  SecretConfigurationError,
  SecretNotFoundError,
  type VaultClient,
} from './index';

// The web tier reads two secrets, `session-secret` and `edge-origin`, from Key Vault through the app's
// managed identity (DEC-1304). Nothing here reaches a network: the vault is a fake and so is the clock.

const VAULT = 'https://diucs-test.vault.azure.net';
const VALUE = 'CANARY-vault-value-0f3a9c7d';
const PLAIN = 'CANARY-plain-env-value-77aa';
const SECONDS = 1000;

type Fake = VaultClient & { getSecret: ReturnType<typeof vi.fn> };

function fakeVault(values: Record<string, string> = { 'session-secret': VALUE, 'edge-origin': `${VALUE}-edge` }): Fake {
  const client = {
    getSecret: vi.fn(async (name: string) => {
      const value = values[name];
      if (value === undefined) throw Object.assign(new Error(`secret ${name} was not found`), { statusCode: 404 });
      return { value };
    }),
  };
  return client as unknown as Fake;
}

function failing(statusCode?: number, message = 'vault said no'): Fake {
  return { getSecret: vi.fn(async () => { throw Object.assign(new Error(message), statusCode === undefined ? {} : { statusCode }); }) } as unknown as Fake;
}

let now = 0;
const clock = () => now;
let warnings: string[] = [];

function build(env: Record<string, string | undefined>, client?: VaultClient) {
  return createSecrets({ env, client, now: clock, warn: (message) => warnings.push(message) });
}

beforeEach(() => {
  now = 1_000_000;
  warnings = [];
});
afterEach(() => vi.restoreAllMocks());

describe('without DIUCS_KEY_VAULT_URL (local runs and tests)', () => {
  it('reads the plain variables as it did before', async () => {
    const client = fakeVault();
    const secrets = build({ SESSION_SECRET: PLAIN, DIUCS_EDGE_ORIGIN_SECRET: `${PLAIN}-edge` }, client);
    expect(secrets.vaultConfigured()).toBe(false);
    expect(await secrets.getSecret('session-secret')).toBe(PLAIN);
    expect(await secrets.getSecret('edge-origin')).toBe(`${PLAIN}-edge`);
    expect(client.getSecret).not.toHaveBeenCalled();
  });

  it('says not found for an unset or empty variable and for a name it has no variable for', async () => {
    const secrets = build({ SESSION_SECRET: '' });
    await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretNotFoundError);
    await expect(secrets.getSecret('edge-origin')).rejects.toBeInstanceOf(SecretNotFoundError);
    await expect(secrets.getSecret('link-token')).rejects.toBeInstanceOf(SecretNotFoundError);
  });

  it('never builds a vault client', async () => {
    const createClient = vi.fn();
    const secrets = createSecrets({ env: { SESSION_SECRET: PLAIN }, createClient, now: clock });
    await secrets.getSecret('session-secret');
    expect(createClient).not.toHaveBeenCalled();
  });
});

describe('with DIUCS_KEY_VAULT_URL', () => {
  const env = { DIUCS_KEY_VAULT_URL: VAULT };

  it('reads the secret from the vault, by its own name', async () => {
    const client = fakeVault();
    const secrets = build(env, client);
    expect(secrets.vaultConfigured()).toBe(true);
    expect(await secrets.getSecret('session-secret')).toBe(VALUE);
    expect(client.getSecret).toHaveBeenCalledWith('session-secret');
  });

  it('builds the client once, from the URL, on first use', async () => {
    const client = fakeVault();
    const createClient = vi.fn(async () => client);
    const secrets = createSecrets({ env, createClient, now: clock });
    expect(createClient).not.toHaveBeenCalled();
    await secrets.getSecret('session-secret');
    await secrets.getSecret('edge-origin');
    expect(createClient).toHaveBeenCalledTimes(1);
    expect(createClient).toHaveBeenCalledWith(VAULT);
  });

  it('does not keep a client it could not build', async () => {
    const client = fakeVault();
    const createClient = vi.fn().mockRejectedValueOnce(new Error('no identity')).mockResolvedValue(client);
    const secrets = createSecrets({ env, createClient, now: clock });
    await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
    expect(await secrets.getSecret('session-secret')).toBe(VALUE);
    expect(createClient).toHaveBeenCalledTimes(2);
  });

  it.each(['http://diucs-test.vault.azure.net', 'not a url', 'https://', 'ftp://x.test'])(
    'refuses %j as the vault URL, before any call',
    async (url) => {
      const client = fakeVault();
      const secrets = build({ DIUCS_KEY_VAULT_URL: url }, client);
      await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
      expect(client.getSecret).not.toHaveBeenCalled();
    },
  );

  describe('the cache', () => {
    it('serves a value from memory for 600 seconds, then reads again', async () => {
      const client = fakeVault();
      const secrets = build(env, client);
      await secrets.getSecret('session-secret');
      now += 599 * SECONDS;
      await secrets.getSecret('session-secret');
      expect(client.getSecret).toHaveBeenCalledTimes(1);
      now += 1 * SECONDS;
      await secrets.getSecret('session-secret');
      expect(client.getSecret).toHaveBeenCalledTimes(2);
    });

    it('keeps one entry per name', async () => {
      const client = fakeVault();
      const secrets = build(env, client);
      await secrets.getSecret('session-secret');
      await secrets.getSecret('edge-origin');
      await secrets.getSecret('session-secret');
      expect(client.getSecret).toHaveBeenCalledTimes(2);
    });

    it('takes the time to live from DIUCS_SECRET_CACHE_SECONDS', async () => {
      const client = fakeVault();
      const secrets = build({ ...env, DIUCS_SECRET_CACHE_SECONDS: '30' }, client);
      await secrets.getSecret('session-secret');
      now += 29 * SECONDS;
      await secrets.getSecret('session-secret');
      expect(client.getSecret).toHaveBeenCalledTimes(1);
      now += 1 * SECONDS;
      await secrets.getSecret('session-secret');
      expect(client.getSecret).toHaveBeenCalledTimes(2);
    });

    it.each(['abc', '-1', '1.5', '86401'])('refuses DIUCS_SECRET_CACHE_SECONDS=%j, naming the variable', async (value) => {
      const secrets = build({ ...env, DIUCS_SECRET_CACHE_SECONDS: value }, fakeVault());
      const error = await secrets.getSecret('session-secret').catch((e: unknown) => e);
      expect(error).toBeInstanceOf(SecretConfigurationError);
      expect((error as Error).message).toContain('DIUCS_SECRET_CACHE_SECONDS');
    });

    it('refuses DIUCS_SECRET_STALE_SECONDS that is not a whole number of seconds', async () => {
      const secrets = build({ ...env, DIUCS_SECRET_STALE_SECONDS: 'soon' }, fakeVault());
      const error = await secrets.getSecret('session-secret').catch((e: unknown) => e);
      expect(error).toBeInstanceOf(SecretConfigurationError);
      expect((error as Error).message).toContain('DIUCS_SECRET_STALE_SECONDS');
    });

    it('asks the vault once for callers that arrive together', async () => {
      const client = fakeVault();
      const secrets = build(env, client);
      const [a, b, c] = await Promise.all([
        secrets.getSecret('session-secret'),
        secrets.getSecret('session-secret'),
        secrets.getSecret('session-secret'),
      ]);
      expect([a, b, c]).toEqual([VALUE, VALUE, VALUE]);
      expect(client.getSecret).toHaveBeenCalledTimes(1);
    });
  });

  describe('when the vault fails', () => {
    it('never caches a failure: the next call asks again', async () => {
      const calls: number[] = [];
      const client = {
        getSecret: vi.fn(async () => {
          calls.push(calls.length);
          if (calls.length === 1) throw Object.assign(new Error('throttled'), { statusCode: 429 });
          return { value: VALUE };
        }),
      } as unknown as Fake;
      const secrets = build(env, client);
      await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
      expect(await secrets.getSecret('session-secret')).toBe(VALUE);
      expect(client.getSecret).toHaveBeenCalledTimes(2);
    });

    it('never caches a miss', async () => {
      const values: Record<string, string> = {};
      const client = fakeVault(values);
      const secrets = build(env, client);
      await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretNotFoundError);
      values['session-secret'] = VALUE;
      expect(await secrets.getSecret('session-secret')).toBe(VALUE);
    });

    it('says not found for a 404 and a configuration error for anything else', async () => {
      await expect(build(env, failing(404)).getSecret('session-secret')).rejects.toBeInstanceOf(SecretNotFoundError);
      for (const status of [401, 403, 429, 500, undefined]) {
        await expect(build(env, failing(status)).getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
      }
    });

    it('treats an answer with no value, or an empty one, as not found', async () => {
      const none = { getSecret: vi.fn(async () => ({})) } as unknown as Fake;
      const empty = { getSecret: vi.fn(async () => ({ value: '' })) } as unknown as Fake;
      await expect(build(env, none).getSecret('session-secret')).rejects.toBeInstanceOf(SecretNotFoundError);
      await expect(build(env, empty).getSecret('session-secret')).rejects.toBeInstanceOf(SecretNotFoundError);
    });

    describe('stale-if-error', () => {
      async function expiredAfterGood(extra: Record<string, string> = {}) {
        let fail = false;
        const client = {
          getSecret: vi.fn(async () => {
            if (fail) throw Object.assign(new Error('vault is down'), { statusCode: 503 });
            return { value: VALUE };
          }),
        } as unknown as Fake;
        const secrets = build({ ...env, ...extra }, client);
        await secrets.getSecret('session-secret');
        now += 600 * SECONDS;
        return { secrets, client, down: () => { fail = true; }, up: () => { fail = false; } };
      }

      it('serves the earlier good value for 3600 seconds past its expiry, with a warning that names the secret only', async () => {
        const { secrets, down } = await expiredAfterGood();
        down();
        expect(await secrets.getSecret('session-secret')).toBe(VALUE);
        expect(warnings).toHaveLength(1);
        expect(warnings[0]).toContain('session-secret');
        expect(warnings[0]).not.toContain(VALUE);
        expect(warnings[0]).not.toContain('vault is down');
        now += 3599 * SECONDS;
        expect(await secrets.getSecret('session-secret')).toBe(VALUE);
      });

      it('fails closed once the stale window has passed', async () => {
        const { secrets, down } = await expiredAfterGood();
        down();
        now += 3600 * SECONDS;
        await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
      });

      it('goes back to the vault on every call while stale, and takes the fresh value when it returns', async () => {
        const { secrets, client, down, up } = await expiredAfterGood();
        down();
        await secrets.getSecret('session-secret');
        await secrets.getSecret('session-secret');
        expect(client.getSecret).toHaveBeenCalledTimes(3);
        up();
        expect(await secrets.getSecret('session-secret')).toBe(VALUE);
        down();
        expect(await secrets.getSecret('session-secret')).toBe(VALUE); // fresh again, from the cache
        expect(client.getSecret).toHaveBeenCalledTimes(4);
      });

      it('takes the window from DIUCS_SECRET_STALE_SECONDS', async () => {
        const { secrets, down } = await expiredAfterGood({ DIUCS_SECRET_STALE_SECONDS: '60' });
        down();
        now += 59 * SECONDS;
        expect(await secrets.getSecret('session-secret')).toBe(VALUE);
        now += 1 * SECONDS;
        await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
      });

      it('holds no stale value for a secret it never read', async () => {
        const { secrets, down } = await expiredAfterGood();
        down();
        await expect(secrets.getSecret('edge-origin')).rejects.toBeInstanceOf(SecretConfigurationError);
      });
    });
  });

  describe('the name rule', () => {
    it.each([
      '', 'Session-Secret', 'session_secret', 'session--secret', '-session', 'session-', 'a/b', 'twilio/a/b', 'a b', 'a.b',
      '../x', 'x?api-version=1', 'é', 'a'.repeat(128),
    ])('refuses %j before the vault is called, as not found', async (name) => {
      const client = fakeVault();
      const secrets = build(env, client);
      await expect(secrets.getSecret(name)).rejects.toBeInstanceOf(SecretNotFoundError);
      expect(client.getSecret).not.toHaveBeenCalled();
    });

    it('accepts lower-case letters, digits and single hyphens', () => {
      for (const name of ['session-secret', 'edge-origin', 'a', 'a1', 'a-1-b', '9', 'a'.repeat(127)]) expect(isSecretName(name), name).toBe(true);
      for (const name of ['', 'A', 'a--b', '-a', 'a-', 'a_b', 'a/b', 'a'.repeat(128)]) expect(isSecretName(name), name).toBe(false);
    });
  });

  describe('a plain variable beside the vault', () => {
    it.each(['SESSION_SECRET', 'DIUCS_EDGE_ORIGIN_SECRET'])('refuses to serve when %s is set, naming it and never its value', async (variable) => {
      const client = fakeVault();
      const secrets = build({ ...env, [variable]: PLAIN }, client);
      for (const name of ['session-secret', 'edge-origin']) {
        const error = await secrets.getSecret(name).catch((e: unknown) => e);
        expect(error).toBeInstanceOf(SecretConfigurationError);
        expect((error as Error).message).toContain(variable);
        expect((error as Error).message).not.toContain(PLAIN);
      }
      expect(client.getSecret).not.toHaveBeenCalled();
    });

    it('does not mind an empty variable', async () => {
      const secrets = build({ ...env, SESSION_SECRET: '' }, fakeVault());
      expect(await secrets.getSecret('session-secret')).toBe(VALUE);
    });

    it('refuses a variable that appears after the first read', async () => {
      const mutable: Record<string, string | undefined> = { ...env };
      const secrets = build(mutable, fakeVault());
      await secrets.getSecret('session-secret');
      mutable.SESSION_SECRET = PLAIN;
      await expect(secrets.getSecret('session-secret')).rejects.toBeInstanceOf(SecretConfigurationError);
    });
  });

  describe('no leak', () => {
    it('keeps the value out of every log, thrown error and serialised form, on every path', async () => {
      const spies = [vi.spyOn(console, 'warn'), vi.spyOn(console, 'error'), vi.spyOn(console, 'log'), vi.spyOn(console, 'info')].map((s) => s.mockImplementation(() => {}));
      const seen: string[] = [];
      const record = (value: unknown) => {
        if (value instanceof Error) seen.push(value.message, value.stack ?? '', String(value), JSON.stringify(value), JSON.stringify(Object.getOwnPropertyNames(value).map((k) => (value as unknown as Record<string, unknown>)[k])));
        else seen.push(String(value));
      };

      // A vault that echoes the value into its own error text, an outage after a good read, a refused name,
      // a plain variable beside the vault, a bad URL and a bad time to live.
      const echo = { getSecret: vi.fn(async () => { throw Object.assign(new Error(`the value is ${VALUE}`), { statusCode: 500 }); }) } as unknown as Fake;
      record(await createSecrets({ env, client: echo, now: clock }).getSecret('session-secret').catch((e: unknown) => e));

      let down = false;
      const flaky = { getSecret: vi.fn(async () => { if (down) throw new Error(`down ${VALUE}`); return { value: VALUE }; }) } as unknown as Fake;
      const lib = createSecrets({ env, client: flaky, now: clock });
      await lib.getSecret('session-secret');
      now += 700 * SECONDS;
      down = true;
      await lib.getSecret('session-secret');
      now += 4000 * SECONDS;
      record(await lib.getSecret('session-secret').catch((e: unknown) => e));

      record(await createSecrets({ env, client: fakeVault(), now: clock }).getSecret('Bad Name').catch((e: unknown) => e));
      record(await createSecrets({ env: { ...env, SESSION_SECRET: VALUE }, client: fakeVault(), now: clock }).getSecret('session-secret').catch((e: unknown) => e));
      record(await createSecrets({ env: { ...env, DIUCS_SECRET_CACHE_SECONDS: VALUE }, client: fakeVault(), now: clock }).getSecret('session-secret').catch((e: unknown) => e));
      record(await createSecrets({ env: { DIUCS_KEY_VAULT_URL: VALUE }, client: fakeVault(), now: clock }).getSecret('session-secret').catch((e: unknown) => e));
      record(await createSecrets({ env: { SESSION_SECRET: VALUE }, now: clock }).getSecret('edge-origin').catch((e: unknown) => e));

      const logged = [...spies.flatMap((s) => s.mock.calls.flat().map(String)), ...warnings];
      for (const text of [...seen, ...logged]) expect(text).not.toContain(VALUE);
      expect(seen.length).toBeGreaterThan(5);
    });

    it('logs through console.warn by default, with the name only', async () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      let down = false;
      const client = { getSecret: vi.fn(async () => { if (down) throw new Error('boom'); return { value: VALUE }; }) } as unknown as Fake;
      const secrets = createSecrets({ env, client, now: clock });
      await secrets.getSecret('session-secret');
      now += 700 * SECONDS;
      down = true;
      await secrets.getSecret('session-secret');
      expect(warn).toHaveBeenCalledTimes(1);
      expect(String(warn.mock.calls[0]?.[0])).toContain('session-secret');
      expect(JSON.stringify(warn.mock.calls)).not.toContain(VALUE);
    });
  });
});

describe('the default client', () => {
  it('is built from the Azure SDK and the default credential without calling the network', async () => {
    const secrets = createSecrets({ env: { DIUCS_KEY_VAULT_URL: VAULT }, now: clock });
    const fetch = vi.spyOn(globalThis, 'fetch');
    // The first read would reach Key Vault, so only the factory is exercised here.
    const { createVaultClient } = await import('./client');
    const client = await createVaultClient(VAULT);
    expect(typeof client.getSecret).toBe('function');
    expect(fetch).not.toHaveBeenCalled();
    expect(secrets.vaultConfigured()).toBe(true);
  });
});
