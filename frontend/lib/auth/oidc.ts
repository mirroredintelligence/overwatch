// STUB (red commit): replaced in the implementation commit.
export type Binding = { directoryId: string; tenantId: string; platform: boolean };

export type EntraConfig = {
  clientId: string;
  clientSecret: string;
  authorityHost: string;
  publicUrl: string;
  bindings: Binding[];
};

export type Transaction = { state: string; nonce: string; verifier: string; next: string };

export type Identity = { oid: string; directoryId: string; roles: unknown; binding: Binding };

export const REFUSALS = [] as const;
export type Refusal = (typeof REFUSALS)[number];

export class SignInRefused extends Error {
  constructor(readonly reason: string) {
    super('sign-in refused');
  }
}

export function loadEntraConfig(env: Record<string, string | undefined> = process.env): EntraConfig {
  void env;
  throw new Error('not implemented');
}

export function bindingFor(config: EntraConfig, directoryId: string): Binding | undefined {
  void config;
  void directoryId;
  throw new Error('not implemented');
}

export function newTransaction(next: string): Transaction {
  void next;
  throw new Error('not implemented');
}

export function authorizeUrl(config: EntraConfig, transaction: Transaction): URL {
  void config;
  void transaction;
  throw new Error('not implemented');
}

export async function exchangeCode(config: EntraConfig, code: string, transaction: Transaction): Promise<string> {
  void config;
  void code;
  void transaction;
  throw new Error('not implemented');
}

export async function verifyIdToken(
  config: EntraConfig,
  idToken: string,
  nonce: string,
  now: Date = new Date(),
): Promise<Identity> {
  void config;
  void idToken;
  void nonce;
  void now;
  throw new Error('not implemented');
}

export function resetKeyCache(): void {
  throw new Error('not implemented');
}
