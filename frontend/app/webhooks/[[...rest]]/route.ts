import { notFound } from '@/lib/webhooks/forward';

// Every other path under /webhooks, and /webhooks itself, is an empty 404 for every method (DEC-1302): the two
// forwards are the whole allow-list. The two paths have their own routes, which win over this one.
export const dynamic = 'force-dynamic';

export { notFound as GET, notFound as POST, notFound as PUT, notFound as PATCH, notFound as DELETE, notFound as HEAD, notFound as OPTIONS };
