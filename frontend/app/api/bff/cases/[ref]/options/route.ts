import { filterOptions } from '@/lib/advisor/case-api';
import { answer, refuse } from '@/lib/advisor/http';
import { optionsFromParameters } from '@/lib/advisor/options';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';

// The options for one case (W13): the services that meet its hard criteria. One back-end call per
// request, with a key made for that call. The answer is the options view and nothing else.

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;

type Context = { params: Promise<{ ref: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { ref } = await context.params;
    if (!CASE_ID.test(ref)) return refuse(400, 'invalid');
    const parts = optionsFromParameters(await filterOptions(session.backendToken, ref, globalThis.crypto.randomUUID()));
    if (parts === null) return refuse(502, 'exception');
    return answer({ shownAt: new Date().toISOString(), ...parts });
  },
  { roles: [...CASE_ROLES] },
);

export const GET = (request: Request, context: Context) => get(request, context);
