import { isAgeCode, isNeedCode, isUrgencyCode } from '@/lib/advisor/codes';
import { answer, refuse } from '@/lib/advisor/http';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { parseCheck } from '@/lib/advisor/v2/check';
import { V2_ROLES } from '@/lib/advisor/v2/roles';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { routeId } from '@/lib/lead/bffInput';

// Check one patient against one service (DEC-1377). Browse only: nothing is stored and no case is opened. The postcode
// is checked by shape, sent to the back end in the body (never in an address), turned there into its district for this
// one answer, and dropped. It is never echoed.

const MAX_NEEDS = 9;

type Context = { params: Promise<Record<string, string>> };
type Body = { postcode?: unknown; ageBand?: unknown; needs?: unknown; urgency?: unknown };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    let body: Body;
    try {
      body = (await request.json()) as Body;
    } catch {
      return refuse(400, 'invalid');
    }
    const postcode = typeof body.postcode === 'string' ? normalisePostcode(body.postcode) : null;
    const needs = Array.isArray(body.needs) ? [...new Set(body.needs)] : [];
    if (
      postcode === null ||
      !isAgeCode(body.ageBand) ||
      !isUrgencyCode(body.urgency) ||
      needs.length === 0 ||
      needs.length > MAX_NEEDS ||
      !needs.every(isNeedCode)
    ) {
      return refuse(400, 'invalid');
    }
    const { data } = await fhirFetch<unknown>(`/advisor-v2/services/${encodeURIComponent(id)}/check`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      body: { postcode, ageBand: body.ageBand, needs, urgency: body.urgency },
    });
    if (parseCheck(data) === null) return refuse(502, 'exception');
    return answer(data);
  },
  { idScoped: true, roles: [...V2_ROLES] },
);

export const POST = (request: Request, context: Context) => post(request, context);
