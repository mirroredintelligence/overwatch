// Red-commit stub (DEC-010).
export const PAIRING_COOKIE = 'diucs_pairing';
export const DEVICE_COOKIE = 'diucs_device';
export async function rememberPairing(p: { pairingId: string; screenSecret: string }): Promise<void> { void p; }
export async function pairingFrom(request: Request): Promise<{ pairingId: string; screenSecret: string } | null> { void request; return null; }
export async function forgetPairing(): Promise<void> {}
export async function rememberDevice(token: string): Promise<void> { void token; }
export async function deviceFrom(request: Request): Promise<string | null> { void request; return null; }
export async function forgetDevice(): Promise<void> {}
