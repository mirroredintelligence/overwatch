import type { Session } from '@/lib/auth/session';

// Red stub (lesson L139): it answers a session for every input, so each refusal test fails on its
// assertion rather than passing on a null. The implementation commit replaces it.
export function reporterSessionFor(): Session {
  return { role: 'advisor', tenantId: 'x', host: 'x', services: [], sub: 'x', backendToken: 'x', expiresAt: 'x' };
}
