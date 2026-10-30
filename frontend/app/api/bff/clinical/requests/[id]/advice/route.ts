import { randomUUID } from 'node:crypto';
import { validateAdvice } from '@/lib/clinical/advice';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// Gives the advice on a taken request (W44, R13 `$advise`). The advice is checked here as the back end
// checks it; a note is never written to a log. The answer carries the status only.

const NO_STORE = { 'Cache-Control': 'no-store' };
const REQUEST_ID = /^[A-Za-z0-9-]{1,64}$/;

type Context = { params: Promise<{ id: string }> };

function parameters(advice: { advice: string; reason?: string; note?: string }) {
  const parameter: Record<string, unknown>[] = [{ name: 'advice', valueCode: advice.advice }];
  if (advice.reason !== undefined) parameter.push({ name: 'reason', valueCode: advice.reason });
  if (advice.note !== undefined) parameter.push({ name: 'note', valueString: advice.note });
  return { resourceType: 'Parameters', parameter };
}

const post = withBff<Context>(
  async (request, session, context) => {
    const { id } = await context.params;
    if (!REQUEST_ID.test(id)) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }
    const checked = validateAdvice(body);
    if (!checked.ok) return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    await fhirFetch(`/Task/${id}/$advise`, {
      method: 'POST',
      token: session.backendToken,
      body: parameters(checked.value),
      idempotencyKey: randomUUID(),
    });
    return Response.json({ id, status: 'completed' }, { headers: NO_STORE });
  },
  { roles: ['clinical'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
