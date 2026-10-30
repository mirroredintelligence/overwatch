import { notBuilt } from '@/lib/reporter/bff';

// GET /api/bff/invitations/[token] (W33). The back end has no route that looks an invitation up
// yet, so this answers not-built. A token that cannot be an invitation gets the same answer as an
// expired one, so an unknown link tells nobody whether it ever existed.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

type Context = { params: Promise<{ token: string }> };

export async function GET(_request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token)) {
    return Response.json({ state: 'expired' }, { status: 410, headers: NO_STORE });
  }
  return notBuilt();
}
