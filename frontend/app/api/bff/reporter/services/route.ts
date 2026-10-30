import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/reporter/bff';

// GET /api/bff/reporter/services (W38). The reporter's services with their states. The back end has
// no reporter services route yet: not-built.
export const GET = withBff(() => notBuilt(), { roles: ['reporter'] });
