import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { boardChangedFrom } from '@/lib/screens/admin';
import { json } from '@/lib/screens/answers';

// Which board a wall screen shows (TEN-072, W9B's PUT /screens/{deviceId}/board-scope at the back end's
// root): the organisation's own, or a network the server offered in the list. The lead or the tenant
// administrator, CSRF checked (withBff). It is the ONE route that takes a network id in a body
// (`allowNetworkIdInBody`: the top-level key `networkId`, a network id, and no other key naming a tenant,
// a scope or a network). The id is a choice among the networks the back end offered in `GET /screens`
// and never an authority: the back end checks the tenant's membership of it again and answers the one
// 404 for a network the tenant is not an active member of. `If-Match` (the screen's `scopeVersion`) and
// the Idempotency-Key are required and passed on; a stale version is the back end's 412. Only the two
// known fields are forwarded.

const NETWORK_ID = /^net-[a-z0-9][a-z0-9-]{1,26}$/;
const IF_MATCH = /^W\/"\d{1,9}"$/;

type Context = { params: Promise<Record<string, string>> };

function choiceOf(body: unknown): { boardScope: 'tenant' } | { boardScope: 'network'; networkId: string } {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) throw invalidRequest();
  const { boardScope, networkId } = body as Record<string, unknown>;
  if (boardScope === 'tenant' && networkId === undefined) return { boardScope };
  if (boardScope === 'network' && typeof networkId === 'string' && NETWORK_ID.test(networkId)) return { boardScope, networkId };
  throw invalidRequest();
}

const put = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const ifMatch = request.headers.get('if-match');
    if (ifMatch === null || !IF_MATCH.test(ifMatch)) throw invalidRequest();
    const choice = choiceOf(await jsonBody(request));
    const { data } = await fhirFetch<unknown>(`/screens/${encodeURIComponent(id)}/board-scope`, {
      method: 'PUT',
      root: true,
      token: session.backendToken,
      idempotencyKey: key,
      ifMatch,
      body: choice,
    });
    return json(200, boardChangedFrom(data));
  },
  { idScoped: true, roles: ['lead', 'tenant-admin'], allowNetworkIdInBody: true },
);

export const PUT = (request: Request, context: Context) => put(request, context);
