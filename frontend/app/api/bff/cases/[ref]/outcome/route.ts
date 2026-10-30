import { closeCase } from '@/lib/advisor/case-api';
import { idempotencyKeyOf, answer, refuse } from '@/lib/advisor/http';
import { parseOutcomeInput } from '@/lib/advisor/outcome';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';

// Records the outcome and closes the case (W15). The answer is the time the close was recorded; the
// back end's closed record carries no time of its own.

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
type Context = { params: Promise<{ ref: string }> };

const post = withBff<Context>(
  async (request, session, context) => {
    const { ref } = await context.params;
    if (!CASE_ID.test(ref)) return refuse(400, 'invalid');
    const key = idempotencyKeyOf(request);
    if (key === null) return refuse(400, 'invalid');

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return refuse(400, 'invalid');
    }
    const input = parseOutcomeInput(body);
    if (input === null) return refuse(400, 'invalid');

    await closeCase(session.backendToken, ref, input, key);
    return answer({ closedAt: new Date().toISOString() });
  },
  { roles: [...CASE_ROLES] },
);

export const POST = (request: Request, context: Context) => post(request, context);
