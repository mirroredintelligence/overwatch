import type { Role } from '@/lib/auth/session';

// Who may use the Advisor v2 reads (DEC-1362, DEC-1366): the advisor and Advisor v2. The back end admits the same two
// roles and no other; this list and the proxy guard for /advisor/v2 (lib/auth/access.ts) are the front end's side.
export const V2_ROLES: readonly Role[] = ['advisor', 'advisor-v2'];
