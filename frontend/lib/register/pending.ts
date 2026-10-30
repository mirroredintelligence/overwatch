// Stub (red commit).

export const PENDING_COOKIE = 'diucs_register';
export const PENDING_PATH = '/api/bff/identity';

export type Pending = { deviceId: string; inviteToken: string | undefined };

export async function sealPending(_pending: Pending, _now: Date = new Date()): Promise<string> {
  throw new Error('not implemented');
}

export async function unsealPending(_value: string, _now: Date = new Date()): Promise<Pending | null> {
  throw new Error('not implemented');
}

export async function readPending(_request: Request, _now: Date = new Date()): Promise<Pending | null> {
  throw new Error('not implemented');
}
