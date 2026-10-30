import { normaliseHost } from '@/lib/auth/host';
import { createSession } from '@/lib/auth/session';
import { ScreenApiError, type WallGrant } from './server';

/**
 * The wall session: the back end's one-hour token for this screen, which is the screen's own subject,
 * for the tenant the back end signed it for and the host the screen was opened on (DEC-600). A host
 * that is not a host name makes no session.
 */
export async function createWallSession(grant: WallGrant, host: string | null): Promise<void> {
  const own = host === null ? null : normaliseHost(host);
  if (own === null) throw new ScreenApiError('bad-answer');
  await createSession({
    role: 'wall',
    tenantId: grant.tenant,
    host: own,
    services: [],
    sub: grant.sub,
    device: grant.sub,
    backendToken: grant.token,
    expiresAt: grant.expiresAt,
  });
}
