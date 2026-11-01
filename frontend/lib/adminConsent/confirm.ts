import { BackendCallError, callBackend, type BackendCall, type BackendReply } from '@/lib/fhir/hostCall';

// Server-only (DEC-1316 item 5). The return page of an Entra administrator calls the back end to CONFIRM the
// consent. A redirect alone is never proof: the back end asks Microsoft Graph in the administrator's own
// directory whether our app is installed there, and says so. What this module reads from the return address is
// the `state` and what the redirect SAID (`admin_consent`). The `tenant` of the query is never read: the
// tenant is whoever the state names, and the back end looks the invitation up by the state's hash inside it.

export const STATE_SHAPE = /^[a-z0-9][a-z0-9-]{1,30}\.[A-Za-z0-9_-]{43}$/;

export type ConsentOutcome =
  | { kind: 'consented'; organisation: string | null }
  | { kind: 'pending'; reason: string; organisation: string | null }
  | { kind: 'expired'; reason: string }
  | { kind: 'revoked'; reason: string }
  | { kind: 'invalid' }
  | { kind: 'unavailable' };

const CLOSED_REASON = 'This invitation can no longer be used. Ask the person who set up Overwatch to send a new one.';

function textOrNull(value: unknown, max: number): string | null {
  return typeof value === 'string' && value.length <= max ? value : null;
}

/** What the redirect said. Anything but Microsoft's own True or False is not said at all. */
export function saidByRedirect(value: string | undefined): boolean | undefined {
  const word = value?.toLowerCase();
  if (word === 'true') return true;
  if (word === 'false') return false;
  return undefined;
}

export async function confirmConsent(
  input: { state: string | undefined; adminConsent: string | undefined; host: string | null },
  call: (call: BackendCall) => Promise<BackendReply> = callBackend,
): Promise<ConsentOutcome> {
  const { state } = input;
  if (state === undefined || !STATE_SHAPE.test(state)) return { kind: 'invalid' };
  const said = saidByRedirect(input.adminConsent);
  let reply;
  try {
    reply = await call({
      method: 'POST',
      path: '/admin-consent/confirmation',
      host: input.host,
      body: said === undefined ? { state } : { state, adminConsent: said },
    });
  } catch (error) {
    if (error instanceof BackendCallError) return { kind: 'unavailable' };
    throw error;
  }
  if (reply.status === 404) return { kind: 'invalid' };
  if (reply.status !== 200 || typeof reply.body !== 'object' || reply.body === null) return { kind: 'unavailable' };
  const body = reply.body as Record<string, unknown>;
  const reason = textOrNull(body.reason, 600);
  const organisation = textOrNull(body.organisation, 200);
  switch (body.status) {
    case 'consented':
      return { kind: 'consented', organisation };
    case 'pending':
      return reason === null ? { kind: 'unavailable' } : { kind: 'pending', reason, organisation };
    case 'expired':
      return { kind: 'expired', reason: reason ?? CLOSED_REASON };
    case 'revoked':
      return { kind: 'revoked', reason: reason ?? CLOSED_REASON };
    default:
      return { kind: 'unavailable' };
  }
}
