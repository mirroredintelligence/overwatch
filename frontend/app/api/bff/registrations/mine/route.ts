import { withBff } from '@/lib/bff/handler';
import { readMine } from '@/lib/register/backend';
import { bffJson } from '@/lib/register/requests';

// My services (W26): the reporter's own services, with the state and detail the page shows.

const get = withBff(
  async (_request, session) => {
    const services = await readMine(session.backendToken);
    return bffJson(200, {
      services: services.map((service) => ({
        id: service.id,
        serviceName: service.serviceName,
        state: service.state,
        detail: service.detail,
      })),
    });
  },
  { roles: ['reporter'] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
