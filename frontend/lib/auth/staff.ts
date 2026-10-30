import { canAccess, isSamePathOnly, roleHome } from './access';
import type { Role } from './session';

// Staff sign-in rules that do not depend on the provider. Which role a person has is the back end's
// (the tenant's own mapping of directory groups, TEN-043), and so is the back-end token: this module
// maps no app role, mints nothing and reads no signing secret (TEN-044, DEC-134 item 2).

/**
 * Where to go after signing in: `next` when it is a path on this site the role may open (and not the
 * sign-in page itself), otherwise the role's home.
 */
export function safeNext(next: string | null | undefined, role: Role): string {
  if (typeof next !== 'string' || !isSamePathOnly(next)) return roleHome(role);
  const path = next.replace(/[?#].*$/s, '');
  if (path.replace(/\/+$/, '').toLowerCase() === '/sign-in') return roleHome(role);
  return canAccess(role, path) ? next : roleHome(role);
}
