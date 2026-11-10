import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { parametersOf } from '@/lib/lead/parameters';

// Deals with one reply the system could not take in (DEC-1359): "process" puts the stored reply on the queue now,
// "handled" says the lead dealt with it another way. Lead only; the back end checks it again.

type Context = { params: Promise<Record<string, string>> };

const PATHS: Record<string, string> = { process: '$reprocess', handled: '$handled' };

const post = withBff<Context>(
  async (request, session, context) => {
    const sid = await routeId(context, 'sid');
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { action?: unknown } | null;
    const action = typeof body?.action === 'string' && Object.hasOwn(PATHS, body.action) ? body.action : undefined;
    if (action === undefined) throw invalidRequest();

    await fhirFetch<unknown>(`/admin/failed-replies/${encodeURIComponent(sid)}/${PATHS[action]}`, {
      root: true,
      method: 'POST',
      body: parametersOf([]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    return Response.json({ sid, action }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
