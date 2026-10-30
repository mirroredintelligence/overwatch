import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';
import { SERVICE_ID, parseReport } from '@/lib/reporter/answers';
import { json, keyOf, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/reporter/services/[serviceId]/report (W35, W8E). A confirm, a number or closed, from
// the app, to `POST /reporter/services/{id}/report` with the screen's Idempotency-Key (DEC-816). The
// back end decides: a figure out of range is asked for again (200 `outOfRange`), a confirm that cannot
// stand is a 409 `sendNumber` and the third confirm in a row a 409 `confirmLimit`. None of those is
// turned into a success here, and the figure is judged at the time of the request.
type Context = { params: Promise<{ serviceId: string }> };

type Sent = { kind: 'confirm' | 'closed' } | { kind: 'number'; value: number; confirmOutOfRange?: boolean };

function shape(body: unknown): Sent | null {
  if (!onlyFields(body, ['kind', 'value', 'confirmOutOfRange'])) return null;
  if (body.kind === 'confirm' || body.kind === 'closed') return Object.keys(body).length === 1 ? { kind: body.kind } : null;
  if (body.kind !== 'number' || !Number.isInteger(body.value) || (body.value as number) < 0 || (body.value as number) > 999) return null;
  if (body.confirmOutOfRange === undefined) return { kind: 'number', value: body.value as number };
  return typeof body.confirmOutOfRange === 'boolean' ? { kind: 'number', value: body.value as number, confirmOutOfRange: body.confirmOutOfRange } : null;
}

export const POST = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await context.params;
    if (!SERVICE_ID.test(serviceId)) return plain(404, 'not-found');
    const key = keyOf(request);
    const body = shape(await readJson(request));
    if (key === null || body === null) return plain(400, 'invalid');
    return reporterCall(session, `/reporter/services/${serviceId}/report`, {
      body,
      key,
      parse: parseReport,
      onRefused: (error: FhirError) => {
        if (error.status !== 409) return null;
        const refused = parseReport(error.payload);
        return refused !== null && (refused.result === 'sendNumber' || refused.result === 'confirmLimit') ? json(refused, 409) : null;
      },
    });
  },
  { idScoped: true, roles: ['reporter'] },
);
