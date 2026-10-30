import { withBff } from '@/lib/bff/handler';

// Red stub (DEC-010).
const post = withBff(async () => new Response(null, { status: 200 }), { roles: ['lead'] });
export const POST = (request: Request, context: unknown) => post(request, context);
