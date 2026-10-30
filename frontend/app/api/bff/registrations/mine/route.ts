import { withBff } from '@/lib/bff/handler';
import { readMine } from '@/lib/register/backend';
import { myServicesFrom } from '@/lib/register/applicant';
import { bffJson, refuse } from '@/lib/register/requests';

// My services (W26): the applicant's own registrations, with the state and the detail the page shows.
// A registration nobody has sent yet is not listed. The back end's answer is mapped here, and a
// answer that cannot be read is a 503, never an empty list.

const get = withBff(
  async (_request, session) => {
    const services = myServicesFrom(await readMine(session.backendToken));
    if (services === null) return refuse(503, 'unavailable', 'We could not load your registration. Try again later.');
    return bffJson(200, { services });
  },
  { roles: ['reporter'] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
