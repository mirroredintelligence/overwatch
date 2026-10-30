import { list, obj, oneOf, str } from './answers';
import { OPERATOR_ROLES, type OperatorRole } from './session';

// `GET /platform/session` (W9C-routes): `{role, accountRef, expiresAt, permissions[]}`.

export const PERMISSIONS = ['tenants:list', 'tenants:read', 'tenants:provision', 'tenants:lifecycle', 'audit:read', 'support:request'] as const;
export type Permission = (typeof PERMISSIONS)[number];

export type PlatformSession = {
  role: OperatorRole;
  accountRef: string;
  expiresAt: string;
  permissions: Permission[];
};

export function parsePlatformSession(value: unknown): PlatformSession {
  const body = obj(value);
  const permissions = list(body.permissions, 50)
    .map((item) => str(item, 64))
    // A permission this console does not know is not drawn: it is dropped, never trusted.
    .filter((item): item is Permission => (PERMISSIONS as readonly string[]).includes(item));
  return {
    role: oneOf(body.role, OPERATOR_ROLES),
    accountRef: str(body.accountRef, 128),
    expiresAt: str(body.expiresAt, 40),
    permissions,
  };
}
