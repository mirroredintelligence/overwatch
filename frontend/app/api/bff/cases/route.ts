import { openEmptyCase } from '@/lib/advisor/case-api';
import { answer, idempotencyKeyOf, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';

// Opens a call. The browser sends no body and no tenant: the case is opened for the session's own
// organisation (the back-end token says whose). The answer is the case id and nothing else, so the
// front end never holds a back-end record (W10).

const post = withBff(
  async (request, session) => {
    const key = idempotencyKeyOf(request);
    if (key === null) return refuse(400, 'invalid');
    const created = await openEmptyCase(session.backendToken, key);
    return answer({ id: created.id }, 201);
  },
  { roles: [...CASE_ROLES] },
);

// Route handlers receive a context this route does not use.
export const POST = (request: Request) => post(request, undefined);
