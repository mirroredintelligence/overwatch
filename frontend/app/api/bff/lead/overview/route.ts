import { withBff } from '@/lib/bff/handler';

// Red stub (DEC-010).
const get = withBff(async () => new Response(null, { status: 200 }), { roles: ['lead'] });
export const GET = (request: Request, context: unknown) => get(request, context);
