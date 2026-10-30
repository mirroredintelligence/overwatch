import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';
import { parseQueued } from '@/lib/reporter/answers';
import { json, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/push/test (W34, W7C DEC-824, W8E). A test notification to the reporter's own phone, from
// `POST /reporter/push-test`: it names no service, figure or person. No saved subscription is a 409
// `no-subscription`, and three in ten minutes is the limit (a 429 with its wait). An executive may ask for
// one too (W9H, DEC-1043): theirs is the person notification, with the same words and the same answers.
export const POST = withBff(
  async (request, session) => {
    const body = await readJson(request);
    if (!onlyFields(body, [])) return plain(400, 'invalid');
    return reporterCall(session, '/reporter/push-test', {
      body: {},
      parse: parseQueued,
      onRefused: (error: FhirError) =>
        error.status === 409 && (error.payload as { code?: unknown } | undefined)?.code === 'no-subscription' ? json({ code: 'no-subscription' }, 409) : null,
    });
  },
  { roles: ['reporter', 'exec'] },
);
