import { withOperatorBff } from '@/lib/operator/bff';
import { retireBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseRecorded } from '@/lib/operator/views';

// POST /platform/tenants/{id}/numbers/retire: the organisation stops using one of its own numbers. The number stays
// held by the organisation, so no other organisation can take it.
// `recorded: false` means the step was done and the platform chain could not record it: the console says so
// and does not repeat the step.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = retireBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/numbers/retire`, body);
    return Response.json(parseRecorded(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
