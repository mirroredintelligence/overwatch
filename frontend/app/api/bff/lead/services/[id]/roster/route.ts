import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { parseRoster } from '@/lib/lead/roster';

// The duty roster of one service (DEC-1341): who is pre-registered to report for it, and who is on shift now. Lead
// only. The read is checked against the shape the page knows before it is passed on (a malformed answer is an error,
// never an empty roster). Adding takes a name and a mobile number, with CSRF and an Idempotency-Key; the answer names
// the new place and never the number. The back end answers 409 when the person is already on this roster.

type Context = { params: Promise<Record<string, string>> };

const NAME_MIN = 2;
const NAME_MAX = 60;

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const { data } = await fhirFetch<unknown>(`/lead/services/${encodeURIComponent(id)}/roster`, {
      root: true,
      token: session.backendToken,
      cache: 'no-store',
    });
    return Response.json(parseRoster(data), { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as Record<string, unknown> | null;
    const name = typeof body?.name === 'string' ? body.name.trim() : '';
    const mobile = body?.mobile;
    if (name.length < NAME_MIN || name.length > NAME_MAX) throw invalidRequest();
    if (typeof mobile !== 'string' || !isUkMobile(mobile)) throw invalidRequest();
    const { data } = await fhirFetch<{ roleId?: unknown }>(`/lead/services/${encodeURIComponent(id)}/roster`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      idempotencyKey: key,
      body: { name, mobile },
    });
    return Response.json(
      { roleId: typeof data?.roleId === 'string' ? data.roleId : null },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { idScoped: true, roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
export const POST = (request: Request, context: Context) => post(request, context);
