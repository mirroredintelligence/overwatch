// The NHS Organisation Data Service (ORD) for the create-tenant form (DEC-1313). Public reference data, no key and no
// consent. The form searches by the organisation's friendly name (a contains-match, not a fuzzy match: a misspelling
// finds nothing), takes one record, and fills the tenant from it. Only this host is called, from the server.

const ORD = 'https://directory.spineservices.nhs.uk/ORD/2-0-0';
const TIMEOUT_MS = 8_000;
const CODE = /^[A-Z0-9]{3,8}$/;
const NAME_MAX = 120;

/** The organisation types a primary ODS role gives (the form still lets the operator change it). Only the roles
 *  checked against the ORD role list: RO197 NHS TRUST, RO98 CLINICAL COMMISSIONING GROUP (how ORD labels an ICB),
 *  RO76 GP PRACTICE and RO177 PRESCRIBING COST CENTRE (how ORD labels a practice). */
const ORGANISATION_TYPE_BY_ROLE: Readonly<Record<string, string>> = {
  RO197: 'nhs-trust',
  RO98: 'icb',
  RO76: 'gp-practice',
  RO177: 'gp-practice',
};

export type OdsRole = { id: string; name: string; primary: boolean };
export type OdsLink = { relationship: string; code: string; name: string; role: string };
export type OdsSearchHit = { code: string; name: string; postcode: string | null; primaryRole: string | null; status: string };
export type OdsRecord = OdsSearchHit & {
  roles: OdsRole[];
  /** The active relationships (what the organisation is part of, or sits over): the record's own links, active only. */
  links: OdsLink[];
  lastChangedAt: string | null;
  suggestedOrganisationType: string | null;
};

type Json = Record<string, unknown>;

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

/** The friendly name as the search takes it: trimmed, bounded, and never empty. */
export function normaliseOdsName(input: string): string | null {
  const name = input.trim().replace(/\s+/g, ' ');
  return name === '' || name.length > NAME_MAX ? null : name;
}

/** An ODS code as the record takes it (upper case), or null when it cannot be one. */
export function normaliseOdsCode(input: string): string | null {
  const code = input.trim().toUpperCase();
  return CODE.test(code) ? code : null;
}

/** The organisation type a primary role suggests, or null. The operator decides; this only proposes. */
export function organisationTypeForRole(roleId: string | null): string | null {
  return roleId === null ? null : (ORGANISATION_TYPE_BY_ROLE[roleId] ?? null);
}

function parseHit(value: unknown): OdsSearchHit | null {
  const o = value as Json;
  const code = text(o.OrgId);
  const name = text(o.Name);
  if (code === null || name === null) return null;
  return {
    code,
    name,
    postcode: text(o.PostCode),
    primaryRole: text(o.PrimaryRoleId),
    status: text(o.Status) ?? 'Unknown',
  };
}

async function getJson(url: string, fetcher: typeof fetch): Promise<Json | null> {
  try {
    const response = await fetcher(url, { redirect: 'error', signal: AbortSignal.timeout(TIMEOUT_MS), headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    const body = (await response.json()) as unknown;
    return typeof body === 'object' && body !== null ? (body as Json) : null;
  } catch {
    return null;
  }
}

/** Organisations whose name contains the friendly name, active only, at most 20. Null when the service cannot answer. */
export async function searchOds(name: string, fetcher: typeof fetch = fetch): Promise<OdsSearchHit[] | null> {
  const clean = normaliseOdsName(name);
  if (clean === null) return [];
  const body = await getJson(`${ORD}/organisations?Name=${encodeURIComponent(clean)}&Status=Active&Limit=20`, fetcher);
  if (body === null) return null;
  const list = Array.isArray(body.Organisations) ? body.Organisations : [];
  return list.map(parseHit).filter((hit): hit is OdsSearchHit => hit !== null);
}

/** The record's postcode: its own PostCode when given, else the one in its address (GeoLoc.Location.PostCode). */
function postcodeOf(o: Json): string | null {
  const address = ((o.GeoLoc as Json | undefined)?.Location as Json | undefined) ?? {};
  return text(o.PostCode) ?? text(address.PostCode);
}

async function roleName(id: string, fetcher: typeof fetch): Promise<string | null> {
  const body = await getJson(`${ORD}/roles/${encodeURIComponent(id)}`, fetcher);
  const role = (body?.Roles as Json[] | undefined)?.[0];
  return text(role?.displayName);
}

async function organisationName(code: string, fetcher: typeof fetch): Promise<string | null> {
  if (normaliseOdsCode(code) === null) return null;
  const body = await getJson(`${ORD}/organisations/${code}`, fetcher);
  return text((body?.Organisation as Json | undefined)?.Name);
}

/** One organisation with its roles and its active links, or null when there is no such organisation or the service cannot answer. */
export async function recordOds(code: string, fetcher: typeof fetch = fetch): Promise<OdsRecord | null> {
  const clean = normaliseOdsCode(code);
  if (clean === null) return null;
  const body = await getJson(`${ORD}/organisations/${clean}`, fetcher);
  const o = body?.Organisation as Json | undefined;
  if (!o) return null;
  // The record's OrgId is an object (root and extension), not the text the search gives: the code asked for is used.
  const hit = parseHit({ OrgId: clean, Name: o.Name, PostCode: postcodeOf(o), Status: o.Status, PrimaryRoleId: undefined });
  if (hit === null) return null;

  const rolesRaw = ((o.Roles as Json | undefined)?.Role as unknown[] | undefined) ?? [];
  const roles: OdsRole[] = rolesRaw
    .map((r) => r as Json)
    .filter((r) => r.Status === 'Active')
    .map((r) => ({ id: String(r.id), name: '', primary: r.primaryRole === true }));
  const primary = roles.find((r) => r.primary)?.id ?? null;

  const relsRaw = ((o.Rels as Json | undefined)?.Rel as unknown[] | undefined) ?? [];
  const links: OdsLink[] = relsRaw
    .map((r) => r as Json)
    .filter((r) => r.Status === 'Active')
    .map((r) => {
      const target = (r.Target as Json | undefined) ?? {};
      const code = ((target.OrgId as Json | undefined)?.extension as string | undefined) ?? '';
      const role = ((target.PrimaryRoleId as Json | undefined)?.id as string | undefined) ?? '';
      return { relationship: String(r.id ?? ''), code, name: '', role };
    })
    .filter((l) => l.code !== '' && l.relationship !== '');

  // The names of the roles and of the linked organisations, for the screen (one call each, in parallel).
  const roleNames = await Promise.all(roles.map((r) => roleName(r.id, fetcher)));
  const linkNames = await Promise.all(links.map((l) => organisationName(l.code, fetcher)));

  return {
    ...hit,
    primaryRole: primary,
    roles: roles.map((r, i) => ({ ...r, name: roleNames[i] ?? r.id })),
    links: links.map((l, i) => ({ ...l, name: linkNames[i] ?? l.code })),
    lastChangedAt: text(o.LastChangeDate),
    suggestedOrganisationType: organisationTypeForRole(primary),
  };
}
