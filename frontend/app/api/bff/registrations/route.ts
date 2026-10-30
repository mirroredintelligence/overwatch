import { withBff } from '@/lib/bff/handler';
import { readQueue } from '@/lib/register/backend';
import { badRequest } from '@/lib/registration/request';
import { QUEUE_TABS } from '@/lib/registration/model';
import { queueFromBackend } from '@/lib/registration/mapping';
import { bffJson, refuse } from '@/lib/register/requests';
import type { QueueTab } from '@/lib/registration/types';

// The registrations queue (W28): the back end's tabs with their counts, and one tab's rows. Lead only.
// The default tab is waiting. A tab the back end does not have is a 400 and nothing is asked.

function tabOf(request: Request): QueueTab {
  const tab = new URL(request.url).searchParams.get('tab') ?? 'waiting';
  if (!(QUEUE_TABS as readonly string[]).includes(tab)) badRequest();
  return tab as QueueTab;
}

const get = withBff(
  async (request, session) => {
    const tab = tabOf(request);
    const queue = queueFromBackend(await readQueue(session.backendToken, tab));
    if (queue === null) return refuse(503, 'unavailable', 'We could not load the registrations. Try again later.');
    return bffJson(200, queue);
  },
  { roles: ['lead'] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
