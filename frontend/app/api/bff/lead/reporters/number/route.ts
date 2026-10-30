import { withBff } from '@/lib/bff/handler';
import { idempotencyKeyOf, jsonBody } from '@/lib/lead/bffInput';
import { readChangeNumber } from '@/lib/lead/changeNumber';
import { notBuilt } from '@/lib/lead/notBuilt';

// A change of a reporter's number for leave or cover (W18). Lead only, CSRF on the POST. The body is
// checked here first. The back end's change needs the reporter's role id, and no read gives the role for
// a service yet, so the valid request answers 501 and changes nothing (DEC-651).

const post = withBff(
  async (request) => {
    idempotencyKeyOf(request);
    readChangeNumber(await jsonBody(request));
    return notBuilt();
  },
  { roles: ['lead'] },
);

export const POST = (request: Request) => post(request, undefined);
