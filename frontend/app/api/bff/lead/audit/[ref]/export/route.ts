import { withBff } from '@/lib/bff/handler';
import { routeId } from '@/lib/lead/bffInput';
import { fetchReplay } from '@/lib/lead/auditServer';
import { toCsv } from '@/lib/lead/auditCsv';

// The audit replay as a CSV attachment for review (W47). Lead only, not cached.

type Context = { params: Promise<Record<string, string>> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const reference = await routeId(context, 'ref');
    const replay = await fetchReplay(session.backendToken, reference);
    return new Response(toCsv(replay), {
      status: 200,
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="audit-${reference}.csv"`,
        'Cache-Control': 'no-store',
      },
    });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
