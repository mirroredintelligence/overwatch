import { withOperatorBff } from '@/lib/operator/bff';
import { sharedLineBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseRecorded } from '@/lib/operator/views';

// POST /platform/tenants/{id}/numbers/shared: the organisation sends its texts from the platform's shared line (sending
// only). The shared number is never recorded as the organisation's own.
// `recorded: false` means the step was done and the platform chain could not record it.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = sharedLineBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/numbers/shared`, body);
    return Response.json(parseRecorded(data), { status: 201, headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
