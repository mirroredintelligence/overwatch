import type { Role } from '@/lib/auth/session';

// Who may work a call: the advisor only (DEC-860). The back end's case routes admit advisor and
// clinical (DEC-397) and a shift lead is refused there as NotFound, so the page guard for /advisor
// (lib/auth/access.ts) and every advisor BFF route admit the advisor alone, and the guard and the back
// end cannot send a lead to a page that cannot work. A clinical advisor works the clinical pages.
export const CASE_ROLES: readonly Role[] = ['advisor'];
