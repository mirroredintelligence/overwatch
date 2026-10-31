import { withOperatorBff } from '@/lib/operator/bff';
import { recordOds } from '@/lib/operator/ods';

// GET /platform/ods/{code}: one NHS organisation with its roles and active links, for the create-tenant form to show
// before the operator confirms it. Nothing is saved here.
type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (_request, _session, context) => {
    const { code } = await context.params;
    const record = await recordOds(code ?? '');
    if (record === null) return Response.json({ code: 'not-found', message: 'No NHS organisation has that ODS code.' }, { status: 404 });
    return Response.json({ record }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['platform-operator'] },
);

export const GET = (request: Request, context: Context) => handle(request, context);
