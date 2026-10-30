// The shapes the reporter pages read from the BFF. A value that does not match is refused, never
// shown: nothing from the back end is rendered unless it has the expected shape.

export type InvitationState = 'valid' | 'expired' | 'used';

export type Invitation = {
  service: string;
  role: string;
  maskedPhone: string;
  expiresAt: string;
  state: InvitationState;
};

const STATES: readonly InvitationState[] = ['valid', 'expired', 'used'];

export function parseInvitation(value: unknown): Invitation | null {
  if (typeof value !== 'object' || value === null) return null;
  const v = value as Record<string, unknown>;
  const ok =
    typeof v.service === 'string' &&
    typeof v.role === 'string' &&
    typeof v.maskedPhone === 'string' &&
    typeof v.expiresAt === 'string' &&
    typeof v.state === 'string' &&
    (STATES as readonly string[]).includes(v.state);
  if (!ok) return null;
  return {
    service: v.service as string,
    role: v.role as string,
    maskedPhone: v.maskedPhone as string,
    expiresAt: v.expiresAt as string,
    state: v.state as InvitationState,
  };
}
