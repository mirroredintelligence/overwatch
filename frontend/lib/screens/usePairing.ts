// Red-commit stub (DEC-010).
export const POLL_INTERVAL_MS = 3000;
export const RETRY_UNAVAILABLE_MS = 10_000;
export type PairingApi = {
  renew: (signal?: AbortSignal) => Promise<void>;
  start: (signal?: AbortSignal) => Promise<{ pairingId: string; code: string; expiresAt: string }>;
  poll: (id: string, signal?: AbortSignal) => Promise<'waiting' | 'paired' | 'expired' | 'connecting'>;
};
export type PairingView = { kind: 'connecting' } | { kind: 'code'; code: string; expiresAt: string } | { kind: 'throttled' } | { kind: 'unavailable' };
export function usePairing(options: { api: PairingApi; onPaired: () => void }): PairingView {
  void options;
  return { kind: 'connecting' };
}
