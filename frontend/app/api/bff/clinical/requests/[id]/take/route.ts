import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// Takes a waiting request (W44, R13 `$take`). Once taken, no other clinician can; a request taken by
// someone else is a 409, which carries no detail of who.

const NO_STORE = { 'Cache-Control': 'no-store' };
const REQUEST_ID = /^[A-Za-z0-9-]{1,64}$/;

type Context = { params: Promise<{ id: string }> };

const post = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!REQUEST_ID.test(id)) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    const { data } = await fhirFetch<{ businessStatus?: { coding?: { code?: unknown }[] } }>(`/Task/${id}/$take`, {
      method: 'POST',
      token: session.backendToken,
      idempotencyKey: randomUUID(),
    });
    const status = data.businessStatus?.coding?.[0]?.code;
    return Response.json({ id, status: typeof status === 'string' ? status : 'in-progress' }, { headers: NO_STORE });
  },
  { roles: ['clinical'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
