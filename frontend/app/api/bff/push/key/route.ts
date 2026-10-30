import { callLinkApi, hostOf, LinkApiError } from '@/lib/links/server';
import { parsePushKey } from '@/lib/reporter/answers';
import { plain } from '@/lib/reporter/backend';

// GET /api/bff/push/key (W34, W7C DEC-824, W8E). The platform's VAPID public key, from the back end's
// `GET /public/push-key` (tenant by host, no token): the browser needs it to subscribe. It is not a
// secret, and it is the only thing this route answers. The service worker never asks for it: the page
// does, on the All-set step after sign-in (DEC-661). A key the back end has not set, or that is not
// base64url text, is "unavailable": the page then says the save did not happen.
const NO_STORE = { 'Cache-Control': 'no-store' };

export async function GET(request: Request): Promise<Response> {
  try {
    const reply = await callLinkApi({ method: 'GET', path: '/public/push-key', host: hostOf(request) });
    const parsed = reply.status === 200 ? parsePushKey(reply.body) : null;
    if (parsed === null) return plain(503, 'unavailable');
    return Response.json(parsed, { headers: NO_STORE });
  } catch (error) {
    if (error instanceof LinkApiError) return plain(503, 'unavailable');
    throw error;
  }
}
