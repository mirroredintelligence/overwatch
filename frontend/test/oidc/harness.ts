import { createHash, randomBytes } from 'node:crypto';
import { vi } from 'vitest';
import { entraHandlers } from '@/test/msw/handlers/entra';
import { server } from '@/test/msw/server';
import { resetKeyCache } from '@/lib/auth/oidc';
import { CLIENT_ID, CLIENT_SECRET, ENTRA_ENV, HOST, REDIRECT_URI, REDIRECT_URI_B, REDIRECT_URI_C, DIRECTORY_A, DIRECTORY_B } from './constants';
import { FakeEntra, type FakeUser, type Tamper } from './fake-entra';

// Shared set-up for the staff sign-in tests: the environment the sign-in reads,
// a fake Entra whose token and key endpoints MSW answers, and a way to get an ID
// token from it without going through the sign-in.

export async function startFakeEntra(): Promise<FakeEntra> {
  const fake = await FakeEntra.create({
    host: HOST,
    clientId: CLIENT_ID,
    clientSecret: CLIENT_SECRET,
    redirectUri: REDIRECT_URI,
    moreRedirectUris: [REDIRECT_URI_B, REDIRECT_URI_C],
    directories: [DIRECTORY_A, DIRECTORY_B, '33333333-3333-4333-8333-333333333333'],
  });
  server.use(...entraHandlers(fake));
  resetKeyCache();
  return fake;
}

export function stubEntraEnv(overrides: Record<string, string | undefined> = {}) {
  for (const [name, value] of Object.entries({ ...ENTRA_ENV, ...overrides })) {
    if (value === undefined) vi.stubEnv(name, undefined as unknown as string);
    else vi.stubEnv(name, value);
  }
}

/**
 * An ID token as Entra would hand it to the sign-in for `user`, bound to `nonce`.
 * `directory` is the authority the request goes to (a directory id or `organizations`).
 */
export async function idTokenFrom(
  fake: FakeEntra,
  user: FakeUser,
  options: { nonce?: string; directory?: string; tamper?: Tamper } = {},
): Promise<string> {
  const nonce = options.nonce ?? 'nonce-for-tests';
  const directory = options.directory ?? user.tid ?? DIRECTORY_A;
  const verifier = randomBytes(32).toString('base64url');
  const url = new URL(fake.authorizeUrl(directory));
  const params = {
    client_id: CLIENT_ID,
    response_type: 'code',
    redirect_uri: REDIRECT_URI,
    scope: 'openid',
    state: 'state-for-tests',
    nonce,
    code_challenge: createHash('sha256').update(verifier).digest('base64url'),
    code_challenge_method: 'S256',
  };
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const { location } = fake.authorize(url.toString(), user, options.tamper);
  const code = new URL(location).searchParams.get('code') ?? '';
  const result = await fake.token(
    directory,
    new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      code_verifier: verifier,
    }),
  );
  return String(result.body.id_token);
}
