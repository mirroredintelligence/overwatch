import { withBff } from '@/lib/bff/handler';
import { NO_STORE } from '@/lib/networkAdmin/call';
import { listNetworks, ownedNetworks } from '@/lib/networkAdmin/network';

// GET: the networks this organisation's network administrator runs (TEN-080): the ones it owns and is active
// in, from the registry, by name and by the opaque id the server offers. A page uses it to choose when there
// is more than one; the id is a choice among these and never an authority. A tenant that owns none gets an
// empty list, never an error that says why. This route takes no network id.

const get = withBff(
  async (_request, session) =>
    Response.json({ networks: ownedNetworks(await listNetworks(session)).map((n) => ({ id: n.id, name: n.name })) }, { headers: NO_STORE }),
  { roles: ['network-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
