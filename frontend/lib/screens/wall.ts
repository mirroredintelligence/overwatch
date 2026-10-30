import { createSession } from '@/lib/auth/session';
import type { WallGrant } from './server';

/** The wall session: the back end's one-hour token for this screen, which is the screen's own subject. */
export async function createWallSession(grant: WallGrant): Promise<void> {
  await createSession({
    role: 'wall',
    services: [],
    sub: grant.sub,
    device: grant.sub,
    backendToken: grant.token,
    expiresAt: grant.expiresAt,
  });
}
