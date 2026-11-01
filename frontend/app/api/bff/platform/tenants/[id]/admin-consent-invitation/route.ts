import { withOperatorBff } from '@/lib/operator/bff';
import { consentInvitationBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseConsent } from '@/lib/operator/views';

// POST /platform/tenants/{id}/admin-consent-invitation: emails the organisation's Entra administrator the admin
// consent link and records the invitation as pending (DEC-1316). Sending again replaces the earlier link. The
// address goes to the back end and is never echoed. `recorded: false` means the step was done and the platform
// chain could not record it: the console says so and does not repeat the step.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = consentInvitationBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/admin-consent-invitation`, body);
    return Response.json(parseConsent(data), { status: 201, headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
