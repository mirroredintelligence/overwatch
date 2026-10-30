import { onlyFields, plain, readJson } from '@/lib/reporter/backend';
import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { codeRequested, identityOrUnavailable } from '@/lib/reporter/identity';

// POST /api/bff/identity/device-code (W37, W7C DEC-811, DEC-812, W8E). The text code of the 30-day check
// (`reverify`) or of a PIN reset (`pin-reset`), for a phone with no session: the back end finds the
// number through the phone's device, so the browser never holds one. Always 202.
export const POST = preSession(async (request) => {
  const body = await readJson(request);
  if (!onlyFields(body, ['purpose']) || (body.purpose !== 'reverify' && body.purpose !== 'pin-reset')) return plain(400, 'invalid');
  const deviceId = await ensureDevice(request);
  const reply = await identityOrUnavailable(request, { method: 'POST', path: '/identity/device/code', body: { deviceId, purpose: body.purpose } });
  return reply instanceof Response ? reply : codeRequested(reply);
});
