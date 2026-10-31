import { withOperatorBff } from '@/lib/operator/bff';
import { hostBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseRecorded } from '@/lib/operator/views';

// PUT /platform/tenants/{id}/host: sets the tenant's address.
// `recorded: false` means the step was done and the platform chain could not record it: the console says so
// and does not repeat the step.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = hostBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'PUT', `/platform/tenants/${id}/host`, body);
    return Response.json(parseRecorded(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const PUT = (request: Request, context: Context) => handle(request, context);
