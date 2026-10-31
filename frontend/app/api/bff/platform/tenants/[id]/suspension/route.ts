import { withOperatorBff } from '@/lib/operator/bff';
import { suspensionBody } from '@/lib/operator/bodies';
import { parseResumption, parseSuspension } from '@/lib/operator/views';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';

// POST /platform/tenants/{id}/suspension suspends an active tenant (read-only or blocked, with a reason
// word); DELETE resumes a suspended one. `recorded: false` means the step was done and the platform chain
// could not record it: the console says so and does not repeat the step.

type Context = { params: Promise<Record<string, string>> };

const post = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = suspensionBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/suspension`, body);
    return Response.json(parseSuspension(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

const del = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const data = await tenantWrite(session, request, 'DELETE', `/platform/tenants/${id}/suspension`);
    return Response.json(parseResumption(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
export const DELETE = (request: Request, context: Context) => del(request, context);
