import { onlyFields, plain, readJson } from '@/lib/reporter/backend';
import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { codeChecked, identityOrUnavailable } from '@/lib/reporter/identity';

// POST /api/bff/identity/device-code/verify (W37, W7C DEC-812, W8E). The check of the 30-day or PIN-reset
// code; a right code stamps the device, so the PIN routes that follow work.
const CODE = /^\d{6}$/;

export const POST = preSession(async (request) => {
  const body = await readJson(request);
  if (!onlyFields(body, ['purpose', 'code'])) return plain(400, 'invalid');
  if ((body.purpose !== 'reverify' && body.purpose !== 'pin-reset') || typeof body.code !== 'string' || !CODE.test(body.code)) return plain(400, 'invalid');
  const deviceId = await ensureDevice(request);
  const reply = await identityOrUnavailable(request, { method: 'POST', path: '/identity/device/code/verify', body: { deviceId, purpose: body.purpose, code: body.code } });
  return reply instanceof Response ? reply : codeChecked(reply);
});
