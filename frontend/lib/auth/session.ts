// Stub for the red commit (DEC-010). Replaced in the implement commit.

export const ROLES = [
  'reporter',
  'advisor',
  'clinical',
  'lead',
  'owner',
  'exec',
  'wall',
  'anonymous-link',
  'support',
  'audit',
] as const;

export type Role = (typeof ROLES)[number];

export type Session = {
  role: Role;
  services: string[];
  sub: string;
  device?: string;
  backendToken: string;
  expiresAt: string;
};

export const SESSION_COOKIE = 'diucs_session';

export async function sealSession(_session: Session, _now?: Date): Promise<string> {
  throw new Error('sealSession is not implemented yet');
}

export async function unsealSession(_value: string, _now?: Date): Promise<Session | null> {
  throw new Error('unsealSession is not implemented yet');
}

export async function sessionFromRequest(_request: Request, _now?: Date): Promise<Session | null> {
  throw new Error('sessionFromRequest is not implemented yet');
}

export async function getSession(): Promise<Session | null> {
  throw new Error('getSession is not implemented yet');
}

export async function createSession(_session: Session): Promise<void> {
  throw new Error('createSession is not implemented yet');
}

export async function destroySession(): Promise<void> {
  throw new Error('destroySession is not implemented yet');
}
