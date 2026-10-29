import type { Role } from './session';

// STUB (red commit): replaced in the implementation commit.
export type StaffRole = 'advisor' | 'clinical' | 'lead' | 'owner' | 'exec' | 'support';

export function mapRoles(claim: unknown, options: { allowSupport?: boolean } = {}): StaffRole | null {
  void claim;
  void options;
  throw new Error('not implemented');
}

export async function mintBackendToken(
  identity: { oid: string; role: StaffRole; tenantId: string },
  now: Date = new Date(),
): Promise<string> {
  void identity;
  void now;
  throw new Error('not implemented');
}

export function backendTokenExpiresAt(now: Date): Date {
  void now;
  throw new Error('not implemented');
}

export function safeNext(next: string | null | undefined, role: Role): string {
  void next;
  void role;
  throw new Error('not implemented');
}
