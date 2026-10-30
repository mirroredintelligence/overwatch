import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';
import { openBooking } from '@/lib/advisor/bookingServer';

// The advisor's request for a booking (W20). The body names a case and a service and nothing else:
// no tenant, organisation or scope is taken from it, the URL, a header or the query (DEC-130). The
// Idempotency-Key header makes a repeated press one request at the back end.

const NO_STORE = { 'Cache-Control': 'no-store' };
const CASE_REF = /^[A-Za-z0-9._-]{1,64}$/;
const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;
const KEY = /^[A-Za-z0-9-]{16,80}$/;
const FIELDS = ['caseRef', 'serviceId'] as const;

function refuse(status: number, code: string): Response {
  return Response.json({ code }, { status, headers: NO_STORE });
}

const post = withBff(
  async (request, session) => {
    const key = request.headers.get('idempotency-key');
    if (key === null || !KEY.test(key)) return refuse(400, 'invalid');

    let parsed: unknown;
    try {
      parsed = (await request.json()) as unknown;
    } catch {
      return refuse(400, 'invalid');
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return refuse(400, 'invalid');
    const body = parsed as Record<string, unknown>;
    if (!Object.keys(body).every((field) => (FIELDS as readonly string[]).includes(field))) return refuse(400, 'invalid');
    const { caseRef, serviceId } = body;
    if (typeof caseRef !== 'string' || !CASE_REF.test(caseRef)) return refuse(400, 'invalid');
    if (typeof serviceId !== 'string' || !SERVICE_ID.test(serviceId)) return refuse(400, 'invalid');

    try {
      const booking = await openBooking(session, caseRef, serviceId, key);
      return Response.json(booking, { status: 201, headers: NO_STORE });
    } catch (error) {
      if (error instanceof FhirError && error.status === 409) return refuse(409, 'open-request');
      throw error;
    }
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const POST = (request: Request) => post(request, undefined);
