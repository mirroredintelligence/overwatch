import type { IncomingMessage, ServerResponse } from 'node:http';
import { GRANTS, LISTINGS, MEMBER_NETWORKS, MEMBERS, OWNER_NETWORKS, PROJECTION, SHARING } from '@/test/fixtures/network-admin-shapes';
import { TOKEN_ORG_A, TOKEN_ORG_B } from './tokens';

// The network and grant administration routes of the stand-in back end, for the browser tests (TEN-080,
// TEN-081). Like the real routes they answer from the bearer token only: organisation A's token is the owner
// of the one network (`net-sample`); organisation B's is a member of it; any other token is in none, and every
// refusal is the one 404. The answers are the fixtures the back end's own converters wrote
// (test/fixtures/network-admin-shapes.gen.py). Writes answer as the real routes do and change nothing here.

const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }] };
const NETWORK_ID = OWNER_NETWORKS.networks[0]!.id;

function send(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
}

const bearer = (request: IncomingMessage): string | undefined => /^Bearer (.+)$/.exec(request.headers.authorization ?? '')?.[1];

async function bodyOf(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** Answers the `/network-admin/...` routes and returns true; false for any other path. */
export async function handleNetworkAdminRoute(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<boolean> {
  const token = bearer(request);
  const owner = token === TOKEN_ORG_A;
  const member = token === TOKEN_ORG_B;
  const get = request.method === 'GET';

  if (get && pathname === '/network-admin/networks') {
    send(response, 200, owner ? OWNER_NETWORKS : member ? MEMBER_NETWORKS : { networks: [] });
    return true;
  }
  if (get && pathname === '/network-admin/sharing') {
    send(response, member ? 200 : 404, member ? SHARING : NOT_FOUND);
    return true;
  }
  if (get && pathname === '/network-admin/grants') {
    send(response, member ? 200 : 404, member ? { grants: GRANTS.grants.filter((g) => g.organisation_name === 'Sample Area B') } : NOT_FOUND);
    return true;
  }
  const ofNetwork = /^\/network-admin\/network\/([^/]+)\/(members|projection|grants|listings)$/.exec(pathname);
  if (get && ofNetwork !== null) {
    if (!owner || ofNetwork[1] !== NETWORK_ID) send(response, 404, NOT_FOUND);
    else send(response, 200, { members: MEMBERS, projection: PROJECTION, grants: GRANTS, listings: LISTINGS }[ofNetwork[2] as 'members' | 'projection' | 'grants' | 'listings']);
    return true;
  }
  if (request.method !== 'POST') return false;

  const body = await bodyOf(request);
  if (/^\/network-admin\/network\/[^/]+\/members$/.test(pathname)) {
    if (!owner || body.tenant_id !== 'sample-area-c') send(response, 404, NOT_FOUND);
    else send(response, 201, { membership_id: 'mem-new', status: 'invited' });
    return true;
  }
  if (/^\/network-admin\/network\/[^/]+\/members\/[^/]+\/remove$/.test(pathname)) {
    send(response, owner ? 200 : 404, owner ? { status: 'removed', grants_lapsed: 1, listings_withdrawn: 0 } : NOT_FOUND);
    return true;
  }
  if (/^\/network-admin\/network\/[^/]+\/agreement$/.test(pathname)) {
    send(response, owner ? 200 : 404, owner ? { agreement_version: body.version } : NOT_FOUND);
    return true;
  }
  if (/^\/network-admin\/network\/[^/]+\/listings\/[^/]+\/(admit|reinstate|decline|suspend)$/.test(pathname)) {
    send(response, owner ? 200 : 404, owner ? { status: 'done' } : NOT_FOUND);
    return true;
  }
  if (pathname === '/network-admin/grants') {
    send(response, member ? 201 : 404, member ? { id: 'grant-new', status: 'proposed' } : NOT_FOUND);
    return true;
  }
  const grant = /^\/network-admin\/grants\/[^/]+\/(approve|decline|end)$/.exec(pathname);
  if (grant !== null) {
    if (!owner && !member) send(response, 404, NOT_FOUND);
    else send(response, 200, grant[1] === 'approve' ? { effective: false } : { status: grant[1] === 'end' ? 'ended' : 'declined' });
    return true;
  }
  if (/^\/network-admin\/network\/[^/]+\/leave$/.test(pathname)) {
    send(response, member ? 200 : 404, member ? { status: 'left', grants_lapsed: 1, listings_withdrawn: 0 } : NOT_FOUND);
    return true;
  }
  if (/^\/network-admin\/memberships\/[^/]+\/accept$/.test(pathname)) {
    send(response, member ? 200 : 404, member ? { status: 'active' } : NOT_FOUND);
    return true;
  }
  return false;
}
