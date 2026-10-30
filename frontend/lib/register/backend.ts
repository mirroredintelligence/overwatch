// Stub (red commit).
import type { Session } from '@/lib/auth/session';

export type RegistrantSignIn = {
  mobile: string;
  deviceId: string;
  inviteToken: string | undefined;
};

export async function signInRegistrant(_input: RegistrantSignIn): Promise<{ registrationId: string; session: Session }> {
  throw new Error('not implemented');
}
