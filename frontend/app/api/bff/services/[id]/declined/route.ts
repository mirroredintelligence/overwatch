import { answer, idempotencyKeyOf, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { type DeclineReason, postDeclined } from '@/lib/advisor/service-api';
import { withBff } from '@/lib/bff/handler';

// "They declined" (W14): why a service that showed capacity said no. For a conversation with the
// service; it is not used to assess an advisor.

const SERVICE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const REASONS: readonly DeclineReason[] = ['full', 'outside-criteria', 'staffing-or-transport', 'other'];

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
    const reason = body.reason;
    if (typeof caseId !== 'string' || !CASE_ID.test(caseId)) return refuse(400, 'invalid');
    if (!REASONS.includes(reason as DeclineReason)) return refuse(400, 'invalid');

    await postDeclined(session.backendToken, id, caseId, reason as DeclineReason, key);
    return answer({ recorded: true }, 201);
  },
  { roles: [...CASE_ROLES] },
);

export const POST = (request: Request, context: Context) => post(request, context);
