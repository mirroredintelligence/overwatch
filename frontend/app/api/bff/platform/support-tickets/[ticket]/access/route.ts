import { withOperatorBff } from '@/lib/operator/bff';
import { codeBody } from '@/lib/operator/bodies';
import { parseAccessOpened, parseSupportTicket } from '@/lib/operator/views';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';

// POST /platform/support-tickets/{ticket}/access opens the access with the one-time code the tenant's
// administrator gave: one tenant, one hour, once. Every refusal (not your ticket, not approved, a wrong, used
// or lapsed code) is the back end's one 404, and so it is here. DELETE ends the access at once. The code is
// in the body of one call and nowhere else: never stored, logged or put in an address.

type Context = { params: Promise<Record<string, string>> };

const post = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'ticket', 'ticket');
    const body = codeBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/support-tickets/${id}/access`, body);
    return Response.json(parseAccessOpened(data), { headers: NO_STORE });
  },
  { roles: ['support'], idScoped: true },
);

const del = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'ticket', 'ticket');
    const data = await tenantWrite(session, request, 'DELETE', `/platform/support-tickets/${id}/access`);
    return Response.json(parseSupportTicket(data), { headers: NO_STORE });
  },
  { roles: ['support'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
export const DELETE = (request: Request, context: Context) => del(request, context);
