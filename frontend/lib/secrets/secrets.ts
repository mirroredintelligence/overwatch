import { createVaultClient, type VaultClient } from './client';
import { SecretConfigurationError, SecretNotFoundError } from './errors';
import { isSecretName } from './names';

// The secrets of the web tier (DEC-1304): `session-secret`, `edge-origin`, `entra-staff-client-secret` and
// `entra-operator-client-secret`, read from Key Vault at run time, cached in memory per process. No secret is in `process.env` when the vault is in use.
//
// - TTL 600 s (DIUCS_SECRET_CACHE_SECONDS). Only a good read is kept; a miss, a refusal or an outage is
//   never kept, so the next call asks again (callers that arrive together share one request).
// - Stale-if-error: when a refresh fails and an earlier good value is held, that value is served for up
//   to 3600 s past its expiry (DIUCS_SECRET_STALE_SECONDS), with a warning that names the secret only.
//   After that the read fails closed. A secret that was never read has nothing to serve.
// - Without DIUCS_KEY_VAULT_URL (local runs and tests) the plain variables work as they always did. With
//   it, a process that also has any of the four plain variables set refuses to serve: a secret in plain
//   configuration is an error, not a fallback.
// - A value is never logged, put in an error, a prop, a response or a trace. Warnings name the secret.
//
// Server only. Nothing under lib/secrets may be imported by a component (eslint.config.mjs).

export { SecretConfigurationError, SecretNotFoundError } from './errors';
export { isSecretName } from './names';
export type { VaultClient } from './client';

/** The web tier's secrets and the variable each one comes from when there is no vault. */
const PLAIN_VARIABLES: Readonly<Record<string, string>> = {
  'session-secret': 'SESSION_SECRET',
  'edge-origin': 'DIUCS_EDGE_ORIGIN_SECRET',
  'entra-staff-client-secret': 'ENTRA_CLIENT_SECRET',
  'entra-operator-client-secret': 'OPERATOR_ENTRA_CLIENT_SECRET',
};

const URL_VARIABLE = 'DIUCS_KEY_VAULT_URL';
const CACHE_VARIABLE = 'DIUCS_SECRET_CACHE_SECONDS';
const STALE_VARIABLE = 'DIUCS_SECRET_STALE_SECONDS';
const DEFAULT_CACHE_SECONDS = 600;
const DEFAULT_STALE_SECONDS = 3600;
const MAX_SECONDS = 86_400;

type Env = Record<string, string | undefined>;

export type SecretsOptions = {
  /** Read at each call, so a change shows. Defaults to `process.env`. */
  env?: Env;
  /** A client to use instead of building one from DIUCS_KEY_VAULT_URL. */
  client?: VaultClient;
  /** How a client is built from the vault URL. Defaults to the Azure SDK with the default credential. */
  createClient?: (url: string) => Promise<VaultClient>;
  /** Milliseconds. Defaults to `Date.now`. */
  now?: () => number;
  /** Where warnings go. They name a secret, never a value. Defaults to `console.warn`. */
  warn?: (message: string) => void;
};

export type Secrets = {
  /** The value of a secret. Rejects with SecretNotFoundError or SecretConfigurationError. */
  getSecret(name: string): Promise<string>;
  /** True when DIUCS_KEY_VAULT_URL is set: the secrets then come from the vault and from nowhere else. */
  vaultConfigured(): boolean;
};

function nonEmpty(value: string | undefined): value is string {
  return value !== undefined && value !== '';
}

function seconds(env: Env, variable: string, fallback: number): number {
  const raw = env[variable];
  if (!nonEmpty(raw)) return fallback;
  const value = /^\d+$/.test(raw) ? Number(raw) : Number.NaN;
  if (!Number.isSafeInteger(value) || value > MAX_SECONDS) {
    throw new SecretConfigurationError(`${variable} must be a whole number of seconds from 0 to ${MAX_SECONDS}.`);
  }
  return value;
}

function vaultUrl(raw: string): string {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new SecretConfigurationError(`${URL_VARIABLE} must be an https URL.`);
  }
  if (parsed.protocol !== 'https:' || parsed.hostname === '') throw new SecretConfigurationError(`${URL_VARIABLE} must be an https URL.`);
  return raw;
}

function statusOf(error: unknown): unknown {
  return typeof error === 'object' && error !== null ? (error as { statusCode?: unknown }).statusCode : undefined;
}

export function createSecrets(options: SecretsOptions = {}): Secrets {
  const now = options.now ?? Date.now;
  const warn = options.warn ?? ((message: string) => console.warn(message));
  const createClient = options.createClient ?? createVaultClient;
  const cache = new Map<string, { value: string; at: number }>();
  const inflight = new Map<string, Promise<string>>();
  let client: VaultClient | undefined = options.client;

  const envOf = (): Env => options.env ?? process.env;
  const vaultConfigured = () => nonEmpty(envOf()[URL_VARIABLE]);

  async function clientFor(url: string): Promise<VaultClient> {
    if (client !== undefined) return client;
    try {
      // Kept only when it was built: a failure is tried again on the next call.
      client = await createClient(url);
      return client;
    } catch {
      throw new SecretConfigurationError('The vault client could not be created.');
    }
  }

  async function fetchFresh(name: string, url: string): Promise<string> {
    const vault = await clientFor(url);
    let answer: { value?: string };
    try {
      answer = await vault.getSecret(name);
    } catch (error) {
      if (statusOf(error) === 404) throw new SecretNotFoundError(name);
      throw new SecretConfigurationError(`The secret ${name} could not be read from the vault.`);
    }
    if (typeof answer.value !== 'string' || answer.value === '') throw new SecretNotFoundError(name);
    return answer.value;
  }

  async function fromVault(name: string, env: Env): Promise<string> {
    for (const variable of Object.values(PLAIN_VARIABLES)) {
      if (nonEmpty(env[variable])) {
        throw new SecretConfigurationError(`${variable} is set while ${URL_VARIABLE} is set: secrets come from the vault only, so remove ${variable}.`);
      }
    }
    if (!isSecretName(name)) throw new SecretNotFoundError();
    const ttl = seconds(env, CACHE_VARIABLE, DEFAULT_CACHE_SECONDS) * 1000;
    const stale = seconds(env, STALE_VARIABLE, DEFAULT_STALE_SECONDS) * 1000;
    const url = vaultUrl(env[URL_VARIABLE] as string);

    const held = cache.get(name);
    const started = now();
    if (held !== undefined && started - held.at < ttl) return held.value;

    let pending = inflight.get(name);
    if (pending === undefined) {
      pending = fetchFresh(name, url)
        .then((value) => {
          cache.set(name, { value, at: now() });
          return value;
        })
        .finally(() => inflight.delete(name));
      inflight.set(name, pending);
    }
    try {
      return await pending;
    } catch (error) {
      if (held !== undefined && started - held.at < ttl + stale) {
        warn(`The secret ${name} could not be refreshed from the vault; the last good value is still in use.`);
        return held.value;
      }
      throw error;
    }
  }

  function fromEnvironment(name: string, env: Env): string {
    const variable = isSecretName(name) ? PLAIN_VARIABLES[name] : undefined;
    const value = variable === undefined ? undefined : env[variable];
    if (!nonEmpty(value)) throw new SecretNotFoundError(isSecretName(name) ? name : undefined, variable);
    return value;
  }

  return {
    vaultConfigured,
    async getSecret(name: string): Promise<string> {
      const env = envOf();
      return vaultConfigured() ? fromVault(name, env) : fromEnvironment(name, env);
    },
  };
}
