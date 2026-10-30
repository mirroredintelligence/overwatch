import type { Role } from '@/lib/auth/session';

// Who may work a call. The same list as the page guard in lib/auth/access.ts for /advisor, so the
// BFF and the pages cannot disagree. The back end's own case roles (DEC-397) are narrower, and the
// difference is recorded in docs/delivery/fragments/W10.md: the back end answers a lead as NotFound.
export const CASE_ROLES: readonly Role[] = ['advisor', 'lead'];
