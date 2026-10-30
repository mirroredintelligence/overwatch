import { withBff } from '@/lib/bff/handler';
import { readAddresses } from '@/lib/register/backend';
import { bffJson, refuse } from '@/lib/register/requests';
import { normalisePostcode } from '@/lib/register/postcode';

// The address lookup for a fixed site (W24). The reporter's session is needed, the postcode is
// normalised before the back end sees it, and only each address's id and label come back.

const MAX_ADDRESSES = 20;

const get = withBff(
  async (request, session) => {
    const values = new URL(request.url).searchParams.getAll('postcode');
    const postcode = values.length === 1 ? normalisePostcode(values[0] ?? '') : null;
    if (postcode === null) return refuse(400, 'invalid', 'Enter a full postcode');
    const found = await readAddresses(session.backendToken, postcode);
    return bffJson(
      200,
      found.slice(0, MAX_ADDRESSES).map((address) => ({ id: address.id, label: address.label })),
    );
  },
  { roles: ['reporter'] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
