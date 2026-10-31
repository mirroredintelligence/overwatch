import { withOperatorBff } from '@/lib/operator/bff';
import { lookupDirectoryId, normaliseLookupDomain } from '@/lib/operator/directoryLookup';

// GET /platform/directory-lookup?domain=: the Entra directory id of an organisation's domain, for the create-tenant
// form (the browser may not call the identity provider itself: the page's policy allows 'self' only). The answer is
// a suggestion the operator checks; nothing is saved by this route.
const handle = withOperatorBff(
  async (request) => {
    const domain = normaliseLookupDomain(new URL(request.url).searchParams.get('domain') ?? '');
    if (domain === null) return Response.json({ code: 'invalid', message: 'Enter a domain name, for example example.nhs.uk.' }, { status: 400 });
    const directoryId = await lookupDirectoryId(domain);
    return Response.json({ domain, directoryId }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['platform-operator'] },
);

export const GET = (request: Request) => handle(request, undefined);
