import { readRequest } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';
import type { Role } from '@/lib/auth/session';

// The state of an advisor's request for advice (W45, DEC-774, DEC-855): waiting, taken or advised, read
// from the back end. The advice is the one the request holds: the choice, the reason, the clinician's
// note and when. A read that fails is a failure, never "waiting": the dialog says it could not read the
// answer. A request about another case than the one in the path is the same 404 as one that is nowhere.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['advisor', 'lead'];
const ID = /^[A-Za-z0-9-]{1,64}$/;

type Context = { params: Promise<{ ref: string; id: string }> };

const notFound = () => Response.json({ code: 'not-found', message: 'We could not find that.' }, { status: 404, headers: NO_STORE });

const get = withBff<Context>(
  async (_request, session, context) => {
    const { ref, id } = await context.params;
    if (!ID.test(ref) || !ID.test(id)) return notFound();
    const found = await readRequest(session, id);
    if (found.caseId !== ref) return notFound();
    // The name of the service the advisor asked about, when they named one (KI-768): the advice reads as
    // about it ("Go ahead with UCR West"). Never an id.
    const service = found.service === null ? {} : { service: found.service };
    if (found.advice !== null) {
      return Response.json(
        {
          state: 'advised',
          ...service,
          advice: found.advice.choice,
          ...(found.advice.reason === null ? {} : { reason: found.advice.reason }),
          ...(found.advice.note === null ? {} : { note: found.advice.note }),
          ...(found.advice.at === null ? {} : { advisedAt: found.advice.at }),
        },
        { headers: NO_STORE },
      );
    }
    if (found.status === 'in-progress') {
      return Response.json({ state: 'taken', ...service, ...(found.returnsAt === null ? {} : { returnsAt: found.returnsAt }) }, { headers: NO_STORE });
    }
    return Response.json({ state: 'waiting', ...service }, { headers: NO_STORE });
  },
  { roles: ROLES, idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
