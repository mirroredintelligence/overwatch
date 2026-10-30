// Red-commit stub (DEC-010).
export class ScreenClientError extends Error {
  kind: 'not-found' | 'throttled' | 'unavailable' | 'unauthorised' | 'invalid' = 'unavailable';
  retryAfterMs: number | null = null;
  field?: 'code' | 'name' | 'location';
  detail?: string;
}
export async function renewSession(signal?: AbortSignal): Promise<void> { void signal; }
export async function startPairing(signal?: AbortSignal): Promise<{ pairingId: string; code: string; expiresAt: string }> { void signal; throw new ScreenClientError(); }
export async function pollPairing(id: string, signal?: AbortSignal): Promise<'waiting' | 'paired' | 'expired' | 'connecting'> { void id; void signal; throw new ScreenClientError(); }
export async function connectScreen(input: { code: string; name: string; location: string | null }, signal?: AbortSignal): Promise<{ name: string; status: 'online'; connectedAt: string }> { void input; void signal; throw new ScreenClientError(); }
