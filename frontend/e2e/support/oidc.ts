import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import {
  CLIENT_ID,
  CLIENT_SECRET,
  DIRECTORY_A,
  DIRECTORY_B,
  DIRECTORY_UNBOUND,
  OID_ADVISOR,
  OID_B,
  OID_LEAD,
} from '@/test/oidc/constants';
import { FakeEntra, type FakeUser, type Tamper } from '@/test/oidc/fake-entra';
import { ENTRA_HOST, ENTRA_PORT, SITE_URL } from './env';

// The fake Entra provider as a real HTTP server, for the staff sign-in browser tests. The person who
// "signs in" is the persona named by the `fake_user` cookie, which a test sets for the provider's
// address, so parallel tests, each in its own browser context, never share a person.

export const ENTRA_COOKIE = 'fake_user';

export const PERSONAS: Record<string, { user: FakeUser; tamper?: Tamper }> = {
  advisor: { user: { oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A } },
  lead: { user: { oid: OID_LEAD, roles: ['DIUCS.Advisor', 'DIUCS.Lead'], tid: DIRECTORY_A } },
  clinical: { user: { oid: OID_LEAD, roles: ['DIUCS.Clinical'], tid: DIRECTORY_A } },
  // A person of another tenant's directory, signing in on this tenant's host: refused, like no role.
  'other-organisation': { user: { oid: OID_B, roles: ['DIUCS.Advisor'], tid: DIRECTORY_B } },
  'no-role': { user: { oid: OID_ADVISOR, roles: ['Some.Other.Role'], tid: DIRECTORY_A } },
  'support-from-a-customer': { user: { oid: OID_ADVISOR, roles: ['DIUCS.Support'], tid: DIRECTORY_A } },
  'unbound-directory': { user: { oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_UNBOUND } },
  'forged-nonce': {
    user: { oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A },
    tamper: { nonce: 'not-the-nonce-that-was-sent' },
  },
};

function cookieOf(request: IncomingMessage, name: string): string | undefined {
  for (const part of (request.headers.cookie ?? '').split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).trim() === name) return part.slice(at + 1).trim();
  }
  return undefined;
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let text = '';
    request.on('data', (chunk: Buffer) => (text += chunk.toString()));
    request.on('end', () => resolve(text));
  });
}

function send(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
}

export async function startFakeEntraServer(): Promise<Server> {
  const fake = await FakeEntra.create({
    host: ENTRA_HOST,
    clientId: CLIENT_ID,
    clientSecret: CLIENT_SECRET,
    redirectUri: `${SITE_URL}/api/bff/auth/entra/callback`,
    directories: [DIRECTORY_A, DIRECTORY_B, DIRECTORY_UNBOUND],
  });

  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? '/', ENTRA_HOST);
    const [, directory = '', ...rest] = url.pathname.split('/');
    const tail = rest.join('/');

    if (url.pathname === '/__requests') return send(response, 200, fake.requests);

    if (request.method === 'GET' && tail === 'oauth2/v2.0/authorize') {
      const persona = PERSONAS[cookieOf(request, ENTRA_COOKIE) ?? ''];
      if (!persona) return send(response, 400, { error: 'no persona chosen for this browser' });
      const { location } = fake.authorize(url.toString(), persona.user, persona.tamper);
      response.writeHead(302, { Location: location, 'Cache-Control': 'no-store' }).end();
      return;
    }
    if (request.method === 'POST' && tail === 'oauth2/v2.0/token') {
      const result = await fake.token(directory, new URLSearchParams(await readBody(request)));
      return send(response, result.status, result.body);
    }
    if (request.method === 'GET' && tail === 'discovery/v2.0/keys') {
      const result = fake.keys(directory);
      return send(response, result.status, result.body);
    }
    send(response, 404, { error: 'not_found' });
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(ENTRA_PORT, '127.0.0.1', resolve);
  });
  return server;
}
