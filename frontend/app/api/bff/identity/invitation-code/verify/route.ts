import { onlyFields, plain, readJson } from '@/lib/reporter/backend';
import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { codeChecked, identityOrUnavailable } from '@/lib/reporter/identity';

// POST /api/bff/identity/invitation-code/verify (W33, W7C DEC-811, W8E). The check of the set-up code:
// the invitation's token and the six digits. The device is the phone's own cookie, never the body, and a
// right code is recorded on it by the back end in the same call. A wrong code says how many tries are
// left; five, or a lapsed code, say a new one is needed.

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;
const CODE = /^\d{6}$/;

export const POST = preSession(async (request) => {
  const body = await readJson(request);
  if (!onlyFields(body, ['invite', 'code'])) return plain(400, 'invalid');
  if (typeof body.invite !== 'string' || !TOKEN_SHAPE.test(body.invite) || typeof body.code !== 'string' || !CODE.test(body.code)) {
    return plain(400, 'invalid');
  }
  const deviceId = await ensureDevice(request);
  const reply = await identityOrUnavailable(request, { method: 'POST', path: `/identity/invitations/${body.invite}/code/verify`, body: { code: body.code, deviceId } });
  return reply instanceof Response ? reply : codeChecked(reply);
});
