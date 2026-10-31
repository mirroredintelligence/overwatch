import { invalidRequest } from '@/lib/lead/bffInput';
import { AGREEMENT_REFERENCE, ORGANISATION_CODE } from './patterns';
import { LISTING_REASONS, type ListingReason } from './views';

// What the browser may send to the network administration routes, checked field by field before any
// call (TEN-080). An unknown field is refused, so nothing the screens do not send reaches the back end;
// a reason is a code, never free text; the agreement's reference and version are all that is stored of it
// (never its content). The organisation code is the one way to name an organisation to invite, and the
// back end's field for it is the tenant's own id: that name never comes from the browser.

type Body = Record<string, unknown>;

function only(body: unknown, allowed: readonly string[]): Body {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) throw invalidRequest();
  for (const key of Object.keys(body)) if (!allowed.includes(key)) throw invalidRequest();
  return body as Body;
}

/** A request that carries no body, or an empty one: an action that takes nothing. */
export async function emptyBody(request: Request): Promise<void> {
  const text = await request.text();
  if (text.trim() === '') return;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw invalidRequest();
  }
  only(parsed, []);
}

export function inviteBody(body: unknown): { tenant_id: string } {
  const b = only(body, ['organisationCode']);
  const code = b.organisationCode;
  if (typeof code !== 'string' || !ORGANISATION_CODE.test(code)) throw invalidRequest();
  return { tenant_id: code };
}

export function agreementBody(body: unknown): { reference: string; version: number } {
  const b = only(body, ['reference', 'version']);
  const { reference, version } = b;
  if (typeof reference !== 'string' || !AGREEMENT_REFERENCE.test(reference)) throw invalidRequest();
  if (typeof version !== 'number' || !Number.isInteger(version) || version < 1 || version > 100000) throw invalidRequest();
  return { reference, version };
}

export function reasonBody(body: unknown): { reason: ListingReason } {
  const b = only(body, ['reason']);
  const { reason } = b;
  if (typeof reason !== 'string' || !(LISTING_REASONS as readonly string[]).includes(reason)) throw invalidRequest();
  return { reason: reason as ListingReason };
}

const SHARED_SCOPES = ['capacity', 'directory', 'criteria'] as const;

/**
 * A proposal to share one kind: the kind and nothing else (the window is the start of now, with no end). The
 * browser's key is `kind`, not the back end's `scope`: the input guard refuses any key that names a scope,
 * because a scope is a tenant's or a network's.
 */
export function proposeBody(body: unknown): { scope: (typeof SHARED_SCOPES)[number] } {
  const b = only(body, ['kind']);
  const { kind } = b;
  if (typeof kind !== 'string' || !(SHARED_SCOPES as readonly string[]).includes(kind)) throw invalidRequest();
  return { scope: kind as (typeof SHARED_SCOPES)[number] };
}

/** The agreement version the administrator read and accepts. */
export function acceptBody(body: unknown): { agreement_version: number } {
  const b = only(body, ['agreementVersion']);
  const { agreementVersion } = b;
  if (typeof agreementVersion !== 'number' || !Number.isInteger(agreementVersion) || agreementVersion < 1 || agreementVersion > 100000) throw invalidRequest();
  return { agreement_version: agreementVersion };
}
