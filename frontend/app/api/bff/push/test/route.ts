import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/reporter/bff';

// POST /api/bff/push/test (W34). No back-end route sends a test notification yet: not-built.
export const POST = withBff(() => notBuilt(), { roles: ['reporter'] });
