import { withOperatorBff } from '@/lib/operator/bff';
import { parseAudit } from '@/lib/operator/views';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';

// GET /platform/audit: a page of the platform chain, oldest first, after a sequence number. The page the
// console asks for is corrected, not refused: 0 and 50 when it names nothing usable, 200 at most.

function whole(raw: string | null, min: number, max: number, fallback: number): number {
  if (raw === null || !/^[0-9]{1,9}$/.test(raw)) return fallback;
  const n = Number(raw);
  return n >= min && n <= max ? n : fallback;
}

const get = withOperatorBff(
  async (request, session) => {
    const query = new URL(request.url).searchParams;
    const afterSeq = whole(query.get('afterSeq'), 0, 1_000_000_000, 0);
    const limit = whole(query.get('limit'), 1, 200, 50);
    const data = await tenantRead(session, `/platform/audit?afterSeq=${afterSeq}&limit=${limit}`);
    return Response.json(parseAudit(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'] },
);

export const GET = (request: Request) => get(request, undefined);
