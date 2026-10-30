import { withBff } from '@/lib/bff/handler';
import { notServed } from '@/lib/registration/backend';
import { badRequest } from '@/lib/registration/request';
import { QUEUE_TABS } from '@/lib/registration/model';
import type { QueueTab } from '@/lib/registration/types';

// The registrations queue (W28): the counts and one tab's items. Lead only.
// The back end does not serve the queue yet (R10), so this answers 503 `not-supported` until it does.

function tabOf(request: Request): QueueTab {
  const tab = new URL(request.url).searchParams.get('tab') ?? 'to-review';
  if (!(QUEUE_TABS as readonly string[]).includes(tab)) badRequest();
  return tab as QueueTab;
}

const get = withBff(
  async (request) => {
    tabOf(request);
    notServed();
  },
  { roles: ['lead'] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
