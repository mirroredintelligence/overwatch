// A stand-in for a back-end bearer token, for tests. It has the shape the back end issues (three
// base64url parts, claims `sub role services tenant epoch aud exp`) and NO valid signature: the front
// end holds no signing secret and never checks one, and the stand-in back end reads the claims only.
// A test that needs to know which tenant a token is for reads it with `claimsOf`.

export type TokenClaims = {
  sub: string;
  role: string;
  services: string[];
  tenant: string;
  epoch: number;
  aud: string;
  iat: number;
  exp: number;
  device?: string;
};

function part(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

export function fakeBackendToken(claims: Partial<TokenClaims> = {}, now: Date = new Date()): string {
  const iat = Math.floor(now.getTime() / 1000);
  const full: TokenClaims = {
    sub: 'stf-00000000000000000000000000000001',
    role: 'advisor',
    services: [],
    tenant: 'trust-a',
    epoch: 1,
    aud: 'diucs-api',
    iat,
    exp: iat + 8 * 3600,
    ...claims,
  };
  return `${part({ alg: 'HS256', typ: 'JWT' })}.${part(full)}.test-signature-not-checked`;
}

export function claimsOf(token: string): Record<string, unknown> {
  const body = token.split('.')[1] ?? '';
  return JSON.parse(Buffer.from(body, 'base64url').toString('utf8')) as Record<string, unknown>;
}
