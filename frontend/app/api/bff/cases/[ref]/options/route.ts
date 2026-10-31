import { filterNetworkOptions, filterOptions, listNetworks } from '@/lib/advisor/case-api';
import { answer, refuse } from '@/lib/advisor/http';
import { type NetworkRead, type OptionView, optionsFromParameters } from '@/lib/advisor/options';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';

// The options for one case (W13, B6): the services of the viewer's own organisation that meet its hard
// criteria, then, read only, the services of the other organisations of the networks it is in (KI-349).
// One back-end call for the own services, with a key made for that call. The network read is separate and
// must never cost the advisor their own list: if it fails, the own services are answered and the answer
// says the network could not be read. A network row carries its organisation's name or it is dropped, so
// no other organisation's service can be taken for the viewer's own. `?only=own` skips the network read
// (the outcome form offers a destination from the viewer's own services only).

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const NETWORK_ID = /^net-[A-Za-z0-9-]{1,60}$/;
/** At most this many networks are read for one display. */
const MAX_NETWORKS = 3;

type Context = { params: Promise<{ ref: string }> };

/** The ids the back end lists, only those shaped like a network id, at most MAX_NETWORKS. Null when the list cannot be read as one. */
function networkIdsOf(value: unknown): string[] | null {
  if (typeof value !== 'object' || value === null) return null;
  const list = (value as { networks?: unknown }).networks;
  if (!Array.isArray(list)) return null;
  const ids: string[] = [];
  for (const item of list) {
    const id = typeof item === 'object' && item !== null ? (item as { id?: unknown }).id : undefined;
    if (typeof id === 'string' && NETWORK_ID.test(id) && !ids.includes(id)) ids.push(id);
    if (ids.length === MAX_NETWORKS) break;
  }
  return ids;
}

/** The other organisations' options, or null when they could not be read. A failure is never an empty list. */
async function networkOptions(token: string, caseId: string): Promise<{ read: NetworkRead; options: OptionView[] }> {
  try {
    const ids = networkIdsOf(await listNetworks(token));
    if (ids === null) return { read: 'unavailable', options: [] };
    if (ids.length === 0) return { read: 'none', options: [] };
    const options: OptionView[] = [];
    for (const id of ids) {
      const parts = optionsFromParameters(await filterNetworkOptions(token, caseId, id, globalThis.crypto.randomUUID()));
      if (parts === null) return { read: 'unavailable', options: [] };
      // A row with no organisation is not a network row: it is dropped, not shown as the viewer's own.
      options.push(...parts.options.filter((option) => option.network !== null));
    }
    return { read: 'shown', options };
  } catch {
    return { read: 'unavailable', options: [] };
  }
}

const get = withBff<Context>(
  async (request, session, context) => {
    const { ref } = await context.params;
    if (!CASE_ID.test(ref)) return refuse(400, 'invalid');
    const own = optionsFromParameters(await filterOptions(session.backendToken, ref, globalThis.crypto.randomUUID()));
    if (own === null) return refuse(502, 'exception');
    const ownOnly = new URL(request.url).searchParams.get('only') === 'own';
    const network = ownOnly ? { read: 'none' as const, options: [] } : await networkOptions(session.backendToken, ref);
    return answer({
      shownAt: new Date().toISOString(),
      ...own,
      // The own services as they are, with a network row's own organisation: never rewritten as ours.
      options: [...own.options.filter((option) => option.network === null), ...network.options],
      network: network.read,
    });
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
