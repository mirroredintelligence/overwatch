import { onlyFields, plain, readJson } from '@/lib/reporter/backend';
import { preSession } from '@/lib/reporter/bff';
import { codeRequested, identityOrUnavailable } from '@/lib/reporter/identity';

// POST /api/bff/identity/invitation-code (W33, W7C DEC-811, W8E). The set-up text code of an invitation.
// The browser holds the link's token, never a number: the back end finds the number through the
// invitation and always answers 202, whatever the token is, and so does this route. The body takes the
// invitation and nothing else; the tenant is the host.

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

export const POST = preSession(async (request) => {
  const body = await readJson(request);
  if (!onlyFields(body, ['invite']) || typeof body.invite !== 'string' || !TOKEN_SHAPE.test(body.invite)) return plain(400, 'invalid');
  const reply = await identityOrUnavailable(request, { method: 'POST', path: `/identity/invitations/${body.invite}/code`, body: {} });
  return reply instanceof Response ? reply : codeRequested(reply);
});
