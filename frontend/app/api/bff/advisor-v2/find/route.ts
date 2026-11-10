import { isAgeCode, isNeedCode, isUrgencyCode } from '@/lib/advisor/codes';
import { answer, refuse } from '@/lib/advisor/http';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { parseFind } from '@/lib/advisor/v2/find';
import { V2_ROLES } from '@/lib/advisor/v2/roles';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// Find a service (DEC-1366). Browse only: no case is opened and nothing is stored. The postcode is checked as the
// call's postcode is (a full UK postcode), sent to the back end in the body (never in an address), turned there
// into its district for this one read, and dropped. It is never echoed in an answer.

const MAX_NEEDS = 9;

type Body = { postcode?: unknown; ageBand?: unknown; needs?: unknown; urgency?: unknown };

const get = withBff(
  async (request, session) => {
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
    const { data } = await fhirFetch<unknown>('/advisor-v2/find', {
      method: 'POST',
      root: true,
      token: session.backendToken,
      body: { postcode, ageBand: body.ageBand, needs, urgency: body.urgency },
    });
    if (parseFind(data) === null) return refuse(502, 'exception');
    return answer(data);
  },
  { roles: [...V2_ROLES] },
);

export const POST = (request: Request) => get(request, undefined);
