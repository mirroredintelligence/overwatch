/**
 * The guard for the synthetic checks (O09). Stub: the tests are written first.
 */

export type SyntheticTarget =
  | { ok: true; baseUrl: string; backendUrl: string; hookToken: string }
  | { ok: false; reason: string };

export type SyntheticEnv = Readonly<Record<string, string | undefined>>;

export function syntheticTarget(_env: SyntheticEnv): SyntheticTarget {
  throw new Error('not implemented');
}

export function sameOrigin(_link: string, _baseUrl: string): boolean {
  throw new Error('not implemented');
}
