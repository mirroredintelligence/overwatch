import { isSamePathOnly } from '@/lib/auth/access';
import { OPERATOR_ROLES, type OperatorRole } from './session';

// Which operator role may open which page of the console, by the path alone (TEN-083). The proxy and the
// sign-in's "where to go next" read this one table. The back end decides again on every call (a support
// person's token is a 404 on an operator-only route), so this is the page guard, not the only one.
//
// The operator has `tenants:*` and `audit:read`; a support person has `tenants:list` and `support:request`
// (GET /platform/session). So the support requests are the support person's and everything that reads a
// tenant's detail, changes its life or reads the chain is the operator's.

export type OperatorAccess =
  | { kind: 'none' }
  | { kind: 'public' }
  | { kind: 'guarded'; roles: readonly OperatorRole[] };

const PREFIX = 'operator';
const BOTH: readonly OperatorRole[] = OPERATOR_ROLES;
const OPERATOR_ONLY: readonly OperatorRole[] = ['platform-operator'];
const SUPPORT_ONLY: readonly OperatorRole[] = ['support'];

/** The path as the router sees it: decoded, dot segments resolved, empty segments dropped. Null when it cannot be decoded. */
function segmentsOf(pathname: string): string[] | null {
  let decoded: string;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  const segments: string[] = [];
  for (const part of decoded.split('/')) {
    if (part === '' || part === '.') continue;
    if (part === '..') segments.pop();
    else segments.push(part);
  }
  return segments;
}

export function operatorAccessFor(pathname: string): OperatorAccess {
  const segments = segmentsOf(pathname);
  // A path that cannot be decoded is guarded for nobody: fail closed.
  if (segments === null) return pathname.toLowerCase().startsWith(`/${PREFIX}`) ? { kind: 'guarded', roles: [] } : { kind: 'none' };
  if (segments[0]?.toLowerCase() !== PREFIX) return { kind: 'none' };
  const area = segments[1]?.toLowerCase();
  if (area === 'sign-in' && segments.length === 2) return { kind: 'public' };
  if (area === 'tenants' || area === 'audit') return { kind: 'guarded', roles: OPERATOR_ONLY };
  if (area === 'support') return { kind: 'guarded', roles: SUPPORT_ONLY };
  return { kind: 'guarded', roles: BOTH };
}

const HOMES: Readonly<Record<OperatorRole, string>> = {
  'platform-operator': '/operator',
  support: '/operator/support',
};

export function operatorHome(role: OperatorRole): string {
  return HOMES[role];
}

/** Where to go after signing in: `next` when it is a console page the role may open, otherwise the role's home. */
export function safeOperatorNext(next: string | null | undefined, role: OperatorRole): string {
  if (typeof next !== 'string' || !isSamePathOnly(next)) return operatorHome(role);
  const path = next.replace(/[?#].*$/s, '');
  const access = operatorAccessFor(path);
  return access.kind === 'guarded' && access.roles.includes(role) ? next : operatorHome(role);
}
