import { answer, idempotencyKeyOf, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { postAdvisorPhoned, type Said } from '@/lib/advisor/service-api';
import { withBff } from '@/lib/bff/handler';

// "I phoned" (W14): what the service said on the phone. The body names the case by its id and the
// answer; the service is in the path. A "not accepting" answer always carries 0. The browser's key is
// passed on, so a double press records once.

const SERVICE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const SAID: readonly Said[] = ['accepting', 'limited', 'not-accepting'];
const MAX_VALUE = 9999; // [ASSUMED] the most a service can report in one answer.

type Context = { params: Promise<{ id: string }> };

const post = withBff<Context>(
  async (request, session, context) => {
    const { id } = await context.params;
    if (!SERVICE_ID.test(id)) return refuse(400, 'invalid');
    const key = idempotencyKeyOf(request);
    if (key === null) return refuse(400, 'invalid');

    let body: Record<string, unknown>;
    try {
      const parsed = (await request.json()) as unknown;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return refuse(400, 'invalid');
      body = parsed as Record<string, unknown>;
    } catch {
      return refuse(400, 'invalid');
    }

    const caseId = body.caseRef;
    const said = body.said;
    if (typeof caseId !== 'string' || !CASE_ID.test(caseId)) return refuse(400, 'invalid');
    if (!SAID.includes(said as Said)) return refuse(400, 'invalid');

    let value: number;
    if (said === 'not-accepting') {
      value = 0;
    } else if (typeof body.value === 'number' && Number.isInteger(body.value) && body.value >= 0 && body.value <= MAX_VALUE) {
      value = body.value;
    } else {
      return refuse(400, 'invalid');
    }

    await postAdvisorPhoned(session.backendToken, id, caseId, said as Said, value, key);
    return answer({ recorded: true }, 201);
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
