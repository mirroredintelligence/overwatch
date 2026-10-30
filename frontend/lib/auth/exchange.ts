import type { Role } from './session';

// Red-commit stub (DEC-010): the tests fail on assertions, not on a missing module.
export type StaffGrant = { token: string; expiresAt: string; role: Role; sub: string };
export type StaffExchange = { kind: 'issued'; grant: StaffGrant } | { kind: 'refused' };

export async function exchangeStaffToken(idToken: string, host: string | null, now: Date = new Date()): Promise<StaffExchange> {
  void idToken;
  void host;
  void now;
  return { kind: 'refused' };
}
