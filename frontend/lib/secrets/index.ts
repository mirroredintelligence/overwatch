import { createSecrets, type Secrets } from './secrets';

// The web tier's secrets, from the process's own environment and the Azure SDK. See secrets.ts for the
// rules; tests build their own with `createSecrets` and a fake vault.

export * from './secrets';

let shared: Secrets | undefined;

function secrets(): Secrets {
  shared ??= createSecrets();
  return shared;
}

/** The value of one of the four web secrets. Never cache the result yourself: this does. */
export function getSecret(name: string): Promise<string> {
  return secrets().getSecret(name);
}

/** True when the secrets come from Key Vault (DIUCS_KEY_VAULT_URL is set). */
export function vaultConfigured(): boolean {
  return secrets().vaultConfigured();
}
