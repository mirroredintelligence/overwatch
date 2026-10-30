import { readCase, updateCase } from '@/lib/advisor/case-api';
import { fromServiceRequest } from '@/lib/advisor/case-fhir';
import { answer, idempotencyKeyOf, refuse } from '@/lib/advisor/http';
import { DISTRICT_PATTERN } from '@/lib/advisor/options';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';

// Choosing a district (W50, W9H DEC-1045). When the postcode was not found, or no service covers its area,
// the advisor picks one of the districts the options screen offered, and the options run again. The back
// end keeps a district alone only through this one extension on the contained Patient (a full postcode is
// still the only thing the case form saves). The route reads the case for its ETag, saves the district
// with it and the screen's key, and answers the case. Only a district is taken: no postcode, no tenant, no
// other field. A case that is not this session's is the one 404 (idScoped).

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const DISTRICT_EXTENSION = 'https://diucs.example/StructureDefinition/postcode-district';

type Context = { params: Promise<{ ref: string }> };

const put = withBff<Context>(
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
    if (typeof body !== 'object' || body === null || Array.isArray(body)) return refuse(400, 'invalid');
    const fields = Object.keys(body);
    const district = (body as { district?: unknown }).district;
    if (fields.length !== 1 || fields[0] !== 'district' || typeof district !== 'string' || !DISTRICT_PATTERN.test(district)) {
      return refuse(400, 'invalid');
    }

    const current = await readCase(session.backendToken, ref);
    if (current.etag === null) return refuse(502, 'exception');
    try {
      const reply = await updateCase(
        session.backendToken,
        ref,
        {
          resourceType: 'ServiceRequest',
          contained: [{ resourceType: 'Patient', id: 'p', extension: [{ url: DISTRICT_EXTENSION, valueCode: district }] }],
        },
        current.etag,
        key,
      );
      const view = fromServiceRequest(reply.data, reply.etag);
      if (view === null) return refuse(502, 'exception');
      return answer(view);
    } catch (error) {
      if (error instanceof FhirError && error.status === 412) return refuse(412, 'conflict');
      throw error;
    }
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const PUT = (request: Request, context: Context) => put(request, context);
