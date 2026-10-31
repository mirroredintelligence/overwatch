import { withOperatorBff } from '@/lib/operator/bff';
import { verificationBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseRecorded } from '@/lib/operator/views';

// POST /platform/tenants/{id}/directory/verification: verifies the directory the tenant's administrator bound.
// `recorded: false` means the step was done and the platform chain could not record it: the console says so
// and does not repeat the step.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = verificationBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/directory/verification`, body);
    return Response.json(parseRecorded(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
