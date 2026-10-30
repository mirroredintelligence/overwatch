import { criteriaFromHistory } from '@/lib/advisor/criteria';
import { answer, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { readCriteriaHistory } from '@/lib/advisor/service-api';
import { withBff } from '@/lib/bff/handler';

// The criteria of one service, for the criteria dialog (W14). Read only: nothing here changes them.

const SERVICE_ID = /^[A-Za-z0-9_-]{1,64}$/;
type Context = { params: Promise<{ id: string }> };

/** The London calendar date, YYYY-MM-DD. Review dates are calendar dates (DEC-038). */
function londonToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/London',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!SERVICE_ID.test(id)) return refuse(400, 'invalid');
    const view = criteriaFromHistory(await readCriteriaHistory(session.backendToken, id), londonToday());
    if (view === null) return refuse(404, 'not-found');
    return answer(view);
  },
  { roles: [...CASE_ROLES] },
);

export const GET = (request: Request, context: Context) => get(request, context);
