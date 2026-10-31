import { withOperatorBff } from '@/lib/operator/bff';
import { normaliseOdsName, searchOds } from '@/lib/operator/ods';

// GET /platform/ods?name=: the NHS organisations whose friendly name contains the text, for the create-tenant form.
// A suggestion the operator picks from; nothing is saved here.
const handle = withOperatorBff(
  async (request) => {
    const name = normaliseOdsName(new URL(request.url).searchParams.get('name') ?? '');
    if (name === null) return Response.json({ code: 'invalid', message: 'Enter the organisation’s name.' }, { status: 400 });
    const results = await searchOds(name);
    if (results === null) return Response.json({ code: 'unavailable', message: 'The NHS directory cannot be reached. Try again.' }, { status: 503 });
    return Response.json({ results }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['platform-operator'] },
);

export const GET = (request: Request) => handle(request, undefined);
