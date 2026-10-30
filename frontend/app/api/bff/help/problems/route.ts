import { withBff } from '@/lib/bff/handler';
import { checkProblem } from '@/lib/help/report';
import type { Role } from '@/lib/auth/session';

// A problem report with the tool (W46). The request is checked here. The back end's use case (U41,
// ReportProblem) is built, but no HTTP route takes it yet: until one is mounted this answers 503 and the
// screen says the report did not send. Nothing is stored or logged here.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'support', 'audit'];

const post = withBff(
  async (request) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }
    const checked = checkProblem(body);
    if (!checked.ok) return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    return Response.json({ code: 'unavailable', message: 'The service is unavailable. Try again shortly.' }, { status: 503, headers: NO_STORE });
  },
  { roles: ROLES },
);

export const POST = (request: Request) => post(request, undefined);
