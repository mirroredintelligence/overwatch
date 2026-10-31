// The operator door's back-end answers (W9C-routes.md, `routes_platform.py`), written from the route
// module's own `*_to_dict` functions, and what the BFF gives the console from each. Sample values only: no
// real organisation, number, account or person. A UK business line is from the Ofcom drama range.

export const OPS_REF = 'ops-0123456789abcdef0123456789abcdef';

/** `GET /platform/tenants` for the operator (the full row) and for a support person (id, name, status only). */
export const RAW_TENANTS_OPERATOR = {
  tenants: [
    { id: 'trust-a', displayName: 'Sample Area A', status: 'active', organisationType: 'nhs-trust', host: 'tenant-a.example.test', activatedAt: '2026-10-01T09:00:00Z' },
    { id: 'trust-b', displayName: 'Sample Area B', status: 'provisioning', organisationType: 'icb', host: null, activatedAt: null },
    { id: 'trust-c', displayName: 'Sample Area C', status: 'suspended', organisationType: 'other', host: 'tenant-c.example.test', activatedAt: '2026-09-01T09:00:00Z' },
  ],
};
export const RAW_TENANTS_SUPPORT = { tenants: RAW_TENANTS_OPERATOR.tenants.map(({ id, displayName, status }) => ({ id, displayName, status })) };
export const VIEW_TENANTS_OPERATOR = RAW_TENANTS_OPERATOR;
export const VIEW_TENANTS_SUPPORT = {
  tenants: RAW_TENANTS_SUPPORT.tenants.map((t) => ({ ...t, organisationType: null, host: null, activatedAt: null })),
};

function detail(over: Record<string, unknown> = {}, tenantOver: Record<string, unknown> = {}) {
  return {
    tenant: {
      id: 'trust-b',
      displayName: 'Sample Area B',
      legalName: 'Sample Area B Organisation',
      organisationType: 'icb',
      countryCode: 'GB',
      timeZone: 'Europe/London',
      odsCode: 'RYY02',
      status: 'provisioning',
      epoch: 1,
      createdAt: '2026-10-20T09:00:00Z',
      activatedAt: null,
      suspendedAt: null,
      suspendMode: null,
      suspendReason: null,
      offboardingStartedAt: null,
      offboardedAt: null,
      purgedAt: null,
      references: { dsa: 'DSA-2026-014', dpia: null, dcb0160: null },
      ...tenantOver,
    },
    host: null,
    directoryId: '11111111-1111-4111-8111-111111111111',
    numbers: [{ e164: '+441632960002', accountSid: 'ACsampleaccount00000000000000000001', status: 'active', testedAt: null, quarantineUntil: null, hasSecret: true, authTokenRef: 'tenants/trust-b/twilio' }],
    activation: { ready: false, blockers: ['Host set', 'Number tested'] },
    ...over,
  };
}

/** A tenant that is still being provisioned, with two things left to do. */
export const RAW_DETAIL_PROVISIONING = detail();
export const RAW_DETAIL_READY = detail({ host: 'tenant-b.example.test', activation: { ready: true, blockers: [] }, numbers: [{ e164: '+441632960002', accountSid: 'ACsampleaccount00000000000000000001', status: 'active', testedAt: '2026-10-21T10:00:00Z', quarantineUntil: null, hasSecret: true }] });
export const RAW_DETAIL_ACTIVE = detail({ host: 'tenant-b.example.test', activation: null }, { status: 'active', activatedAt: '2026-10-22T09:00:00Z' });
export const RAW_DETAIL_SUSPENDED = detail({ host: 'tenant-b.example.test', activation: null }, { status: 'suspended', suspendedAt: '2026-10-25T09:00:00Z', suspendMode: 'read-only', suspendReason: 'contract' });

const { authTokenRef: _drop, ...NUMBER_VIEW_BASE } = RAW_DETAIL_PROVISIONING.numbers[0] as Record<string, unknown>;
void _drop;
export function viewOf(raw: ReturnType<typeof detail>) {
  return {
    tenant: {
      id: raw.tenant.id,
      displayName: raw.tenant.displayName,
      legalName: raw.tenant.legalName,
      organisationType: raw.tenant.organisationType,
      countryCode: raw.tenant.countryCode,
      timeZone: raw.tenant.timeZone,
      odsCode: raw.tenant.odsCode,
      status: raw.tenant.status,
      createdAt: raw.tenant.createdAt,
      activatedAt: raw.tenant.activatedAt,
      suspendedAt: raw.tenant.suspendedAt,
      suspendMode: raw.tenant.suspendMode,
      suspendReason: raw.tenant.suspendReason,
      offboardingStartedAt: raw.tenant.offboardingStartedAt,
      references: raw.tenant.references,
    },
    host: raw.host,
    directoryId: raw.directoryId,
    numbers: raw.numbers.map((n) => ({ e164: n.e164, accountSid: n.accountSid, status: n.status, testedAt: n.testedAt, quarantineUntil: n.quarantineUntil, hasSecret: n.hasSecret })),
    activation: raw.activation,
  };
}
export const VIEW_DETAIL_PROVISIONING = viewOf(RAW_DETAIL_PROVISIONING);
export const VIEW_DETAIL_READY = viewOf(RAW_DETAIL_READY);
export const VIEW_DETAIL_ACTIVE = viewOf(RAW_DETAIL_ACTIVE);
export const VIEW_DETAIL_SUSPENDED = viewOf(RAW_DETAIL_SUSPENDED);
export { NUMBER_VIEW_BASE };

export const RAW_AUDIT = {
  entries: [
    { seq: 1, action: 'operator-signed-in', principalRef: OPS_REF, tenantId: null, accessId: null, snapshot: { role: 'platform-operator' }, at: '2026-10-20T08:00:00Z' },
    { seq: 2, action: 'tenant-created', principalRef: OPS_REF, tenantId: 'trust-b', accessId: null, snapshot: { status: 'provisioning' }, at: '2026-10-20T09:00:00Z' },
    { seq: 3, action: 'support-ticket-requested', principalRef: 'ops-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', tenantId: 'trust-a', accessId: null, snapshot: null, at: '2026-10-21T09:00:00Z' },
  ],
  next: 3,
};
export const VIEW_AUDIT = RAW_AUDIT;
export const RAW_AUDIT_LAST = { entries: [{ seq: 4, action: 'tenant-activated', principalRef: OPS_REF, tenantId: 'trust-b', accessId: null, snapshot: { epoch: 2 }, at: '2026-10-22T09:00:00Z' }], next: null };

function ticket(over: Record<string, unknown> = {}) {
  return {
    id: 'tkt-1',
    tenantId: 'trust-a',
    state: 'pending',
    reasonCode: 'service-fault',
    reason: 'The board shows a service twice',
    reference: 'HD-1042',
    requestedAt: '2026-10-30T08:00:00Z',
    validUntil: '2026-10-31T08:00:00Z',
    decidedAt: null,
    openedAt: null,
    endedAt: null,
    endedBy: null,
    accessId: null,
    ...over,
  };
}
export const RAW_SUPPORT_TICKETS = {
  tickets: [ticket(), ticket({ id: 'tkt-2', tenantId: 'trust-c', state: 'approved', decidedAt: '2026-10-30T08:30:00Z' }), ticket({ id: 'tkt-3', state: 'opened', openedAt: '2026-10-30T09:00:00Z', accessId: 'acc-3' })],
};
function viewTicket(raw: ReturnType<typeof ticket>) {
  const { accessId: _a, ...rest } = raw;
  void _a;
  return rest;
}
export const VIEW_SUPPORT_TICKETS = { tickets: RAW_SUPPORT_TICKETS.tickets.map(viewTicket) };
export { ticket as rawTicket, viewTicket };
