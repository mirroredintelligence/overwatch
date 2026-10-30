import { callLinkApi, hostOf, type LinkReply } from '@/lib/links/server';

// The back end's reporter identity routes (R11, R13), called by the BFF. They sit beside /fhir, at
// the back end's root, and the tenant is the host the browser addressed (DEC-134 item 3), so the
// BFF passes that host and nothing the browser sends. A device id is passed in the body or the
// X-Device-Id header, never in the URL.

export type IdentityReply = LinkReply;

export function identityCall(
  request: Request,
  call: { method: 'GET' | 'POST'; path: string; body?: unknown; headers?: Record<string, string> },
): Promise<IdentityReply> {
  return callLinkApi({ ...call, host: hostOf(request) });
}
