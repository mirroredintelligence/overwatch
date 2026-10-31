// The Key Vault client of the web tier: the SDK, authenticated as the app's managed identity
// (`DefaultAzureCredential`; in Azure `AZURE_CLIENT_ID` names the user-assigned identity, locally it is
// the developer's login). Loaded on first use, so a run without a vault never loads the SDK.

/** The one call the module makes. `SecretClient.getSecret` fits it, and tests supply a fake. */
export type VaultClient = {
  getSecret(name: string): Promise<{ value?: string }>;
};

export async function createVaultClient(url: string): Promise<VaultClient> {
  const [{ SecretClient }, { DefaultAzureCredential }] = await Promise.all([
    import('@azure/keyvault-secrets'),
    import('@azure/identity'),
  ]);
  // A short retry budget: a request is waiting on this, and the cache holds the last good value.
  return new SecretClient(url, new DefaultAzureCredential(), { retryOptions: { maxRetries: 2, retryDelayInMs: 200, maxRetryDelayInMs: 2000 } });
}
