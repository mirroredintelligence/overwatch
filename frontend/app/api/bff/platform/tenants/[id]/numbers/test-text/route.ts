import { withOperatorBff } from '@/lib/operator/bff';
import { testTextBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseTestText } from '@/lib/operator/views';

// POST /platform/tenants/{id}/numbers/test-text: sends one fixed test text from the organisation's line to a mobile the
// operator types. The mobile is personal data: it is in this one body and nowhere else (never a path, a query, a log or an
// answer). The back end marks the line as tested when the text provider accepts the text.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = testTextBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/numbers/test-text`, body);
    return Response.json(parseTestText(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
