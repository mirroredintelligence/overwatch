import type { Role } from './session';

// STUB (red commit): replaced in the implementation commit.
export function rolesFor(pathname: string): readonly Role[] | null {
  void pathname;
  throw new Error('not implemented');
}

export function canAccess(role: Role, pathname: string): boolean {
  void role;
  void pathname;
  throw new Error('not implemented');
}

export function roleHome(role: Role): string {
  void role;
  throw new Error('not implemented');
}

export function isSamePathOnly(value: string): boolean {
  void value;
  throw new Error('not implemented');
}
