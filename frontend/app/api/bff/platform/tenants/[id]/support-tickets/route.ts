import { withOperatorBff } from '@/lib/operator/bff';
import { ticketRequestBody } from '@/lib/operator/bodies';
import { parseSupportTicket } from '@/lib/operator/views';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';

// POST /platform/tenants/{id}/support-tickets: a support person asks to look into one active tenant, with a
// reason code and a plain sentence (no patient data: the restricted alphabet and the six-digit limit are
// checked here and by the back end). A second live request for the tenant is the back end's 409.

type Context = { params: Promise<Record<string, string>> };

const post = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = ticketRequestBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/support-tickets`, body);
    return Response.json(parseSupportTicket(data), { status: 201, headers: NO_STORE });
  },
  { roles: ['support'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
