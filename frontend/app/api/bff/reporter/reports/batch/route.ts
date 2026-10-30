import { withBff } from '@/lib/bff/handler';
import { SERVICE_ID, parseBatch } from '@/lib/reporter/answers';
import { keyOf, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/reporter/reports/batch (W38, W8E). One to ten confirms, each for a different service, in
// one call (DEC-818). Only confirms: a number is the service's own screen. The back end checks every
// service is the reporter's, from the graph, and writes nothing unless all are (one 404); each confirm
// then stands on its own, so one that must send a number does not stop the others.
export const POST = withBff(
  async (request, session) => {
    const key = keyOf(request);
    const body = await readJson(request);
    if (key === null || !onlyFields(body, ['items']) || !Array.isArray(body.items) || body.items.length < 1 || body.items.length > 10) return plain(400, 'invalid');
    const items: { serviceId: string; kind: 'confirm' }[] = [];
    for (const item of body.items as unknown[]) {
      if (!onlyFields(item, ['serviceId', 'kind']) || item.kind !== 'confirm' || typeof item.serviceId !== 'string' || !SERVICE_ID.test(item.serviceId)) {
        return plain(400, 'invalid');
      }
      items.push({ serviceId: item.serviceId, kind: 'confirm' });
    }
    return reporterCall(session, '/reporter/reports/batch', { body: { items }, key, parse: parseBatch });
  },
  { roles: ['reporter'] },
);
