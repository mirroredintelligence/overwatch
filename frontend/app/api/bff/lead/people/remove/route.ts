import { withBff } from '@/lib/bff/handler';
import { idempotencyKeyOf, invalidRequest, jsonBody } from '@/lib/lead/bffInput';
import { notBuilt } from '@/lib/lead/notBuilt';

// Removes a person's access (W42). Lead only, CSRF. The body is checked here. The back end's removal takes a
// reporter's role id, and no read gives the people list that would let the lead pick one, so a valid request
// answers 501 and removes nothing (DEC-651). A person given as free text is refused, never matched.

const REASONS = ['left-service', 'changed-role', 'lost-phone', 'other'] as const;
const ROLE_ID = /^[A-Za-z0-9.-]{1,64}$/;

const post = withBff(
  async (request) => {
    idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { person?: unknown; reason?: unknown } | null;
    if (typeof body?.person !== 'string' || !ROLE_ID.test(body.person)) throw invalidRequest();
    if (!(REASONS as readonly unknown[]).includes(body.reason)) throw invalidRequest();
    return notBuilt();
  },
  { roles: ['lead'] },
);

export const POST = (request: Request) => post(request, undefined);
