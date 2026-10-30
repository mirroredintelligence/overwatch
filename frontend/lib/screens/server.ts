// Red-commit stub (DEC-010).
export class ScreenApiError extends Error {
  kind: string = 'unavailable';
  retryAfter?: string;
}
export async function startPairing(host: string | null): Promise<{ pairingId: string; code: string; expiresAt: string; screenSecret: string }> {
  void host;
  throw new ScreenApiError('stub');
}
export async function claimPairing(host: string | null, id: string, secret: string): Promise<{ status: string; deviceToken?: string | null }> {
  void host; void id; void secret;
  throw new ScreenApiError('stub');
}
export async function exchangeDeviceToken(host: string | null, deviceToken: string, now?: Date): Promise<{ token: string; expiresAt: string; sub: string }> {
  void host; void deviceToken; void now;
  throw new ScreenApiError('stub');
}
export async function connectScreen(
  host: string | null,
  token: string,
  input: { code: string; name: string; location: string | null },
  idempotencyKey: string,
): Promise<{ name: string; status: string }> {
  void host; void token; void input; void idempotencyKey;
  throw new ScreenApiError('stub');
}
