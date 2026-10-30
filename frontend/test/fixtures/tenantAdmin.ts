// The tenant administrator's back-end answers (W9C-routes.md, `routes_tenant.py`), written out by hand from
// the route module's own `*_to_dict` functions, and what the BFF gives the browser from each. Sample values
// only: no real organisation, directory, person or number. `YOU` is the subject the test session carries
// (test/requests.ts `sessionFor` for tenant A), so a draft "made by you" is recognised.

export const YOU = 'stf-trust-a0000000000000000000000000';
export const SOMEONE_ELSE = 'stf-0000000000000000000000000002';
export const THIRD_PERSON = 'stf-0000000000000000000000000003';
export const DIRECTORY = '11111111-1111-4111-8111-111111111111';
export const GROUP = 'cccccccc-0000-4000-8000-000000000001';

/** `GET /tenant/overview`, with the fields the BFF must not pass on (the tenant id, a secret reference, an account sid). */
export const RAW_OVERVIEW = {
  tenant: {
    id: 'trust-a',
    displayName: 'Sample Area A',
    legalName: 'Sample Area A Organisation',
    organisationType: 'nhs-trust',
    countryCode: 'GB',
    timeZone: 'Europe/London',
    odsCode: 'RXX01',
    status: 'active',
    host: 'tenant-a.example.test',
  },
  config: {
    version: 2,
    status: 'current',
    values: { pressureWatchFrom: 4, systemName: 'Capacity A' },
    createdAt: '2026-10-20T09:00:00Z',
    createdByRef: SOMEONE_ELSE,
    effectiveFrom: '2026-10-21T09:00:00Z',
    approvedByRefs: [SOMEONE_ELSE, THIRD_PERSON],
    reasonCode: '',
  },
  contacts: [{ kind: 'coordination-phone', label: 'Access team A', value: '01632 960001' }],
  channels: [
    { id: 'ch-sms', kind: 'sms', provider: 'twilio', status: 'active', senderLabel: 'SampleA', accountSid: 'ACsample', fromAddress: null, fromDisplayName: null, hasSecret: true },
    { id: 'ch-email', kind: 'email', provider: 'smtp', status: 'active', senderLabel: 'Sample A team', accountSid: null, fromAddress: 'noreply@a.example.test', fromDisplayName: 'Sample A', hasSecret: false, secretRef: 'tenants/trust-a/smtp' },
  ],
  retention: [
    { dataClass: 'capacity-reports', keepDays: 730, action: 'summarise' },
    { dataClass: 'audit-chain', keepDays: null, action: 'keep' },
  ],
  bindings: [{ directoryId: DIRECTORY, status: 'verified', verifiedAt: '2026-10-19T10:00:00Z' }],
  mappings: [{ groupObjectId: GROUP, role: 'lead', status: 'active' }],
};

export const VIEW_OVERVIEW = {
  tenant: {
    displayName: 'Sample Area A',
    legalName: 'Sample Area A Organisation',
    organisationType: 'nhs-trust',
    countryCode: 'GB',
    timeZone: 'Europe/London',
    odsCode: 'RXX01',
    status: 'active',
    host: 'tenant-a.example.test',
  },
  config: { version: 2, status: 'current', createdAt: '2026-10-20T09:00:00Z', effectiveFrom: '2026-10-21T09:00:00Z' },
  contacts: [{ kind: 'coordination-phone', label: 'Access team A', value: '01632 960001' }],
  channels: [
    { id: 'ch-sms', kind: 'sms', provider: 'twilio', status: 'active', senderLabel: 'SampleA', fromAddress: null, fromDisplayName: null, hasSecret: true },
    { id: 'ch-email', kind: 'email', provider: 'smtp', status: 'active', senderLabel: 'Sample A team', fromAddress: 'noreply@a.example.test', fromDisplayName: 'Sample A', hasSecret: false },
  ],
  retention: [
    { dataClass: 'capacity-reports', keepDays: 730, action: 'summarise' },
    { dataClass: 'audit-chain', keepDays: null, action: 'keep' },
  ],
  bindings: [{ directoryId: DIRECTORY, status: 'verified', verifiedAt: '2026-10-19T10:00:00Z' }],
  mappings: [{ groupObjectId: GROUP, role: 'lead', status: 'active' }],
};

/** `GET /tenant/settings`: a few rows of the real registry (one of each kind and class). */
export const RAW_SETTINGS = {
  settings: [
    { key: 'pressureWatchFrom', kind: 'int', unit: 'count', default: 3, minimum: 1, maximum: 50, choices: null, allowed: null, safetyClass: 'clinical', scope: 'both', requiredForActivation: false },
    { key: 'twiceADaySecondTime', kind: 'time', unit: 'time-of-day', default: '14:00', minimum: '12:00', maximum: '16:00', choices: null, allowed: null, safetyClass: 'clinical', scope: 'tenant', requiredForActivation: false },
    { key: 'alertDefaultKinds', kind: 'codes', unit: 'codes', default: ['not-updated', 'over-capacity'], minimum: null, maximum: null, choices: null, allowed: ['not-updated', 'over-capacity', 'service-closed'], safetyClass: 'operational', scope: 'tenant', requiredForActivation: false },
    { key: 'alertDefaultNotUpdatedHours', kind: 'int', unit: 'hours', default: 2, minimum: null, maximum: null, choices: [2, 4], allowed: null, safetyClass: 'operational', scope: 'tenant', requiredForActivation: false },
    { key: 'systemName', kind: 'text', unit: 'text', default: null, minimum: 1, maximum: 60, choices: null, allowed: null, safetyClass: 'operational', scope: 'tenant', requiredForActivation: true },
  ],
};

function version(over: Record<string, unknown>) {
  return {
    version: 1,
    status: 'superseded',
    values: {},
    createdAt: '2026-10-10T09:00:00Z',
    createdByRef: SOMEONE_ELSE,
    effectiveFrom: '2026-10-11T09:00:00Z',
    approvedByRefs: [SOMEONE_ELSE],
    reasonCode: '',
    changedKeys: [],
    clinicalKeys: [],
    approvalsRequired: 1,
    replaces: null,
    ...over,
  };
}

/** `GET /tenant/config/versions`, newest first: a draft you wrote, the version in force, the one it replaced. */
export const RAW_VERSIONS = {
  versions: [
    version({ version: 3, status: 'pending-approval', values: { pressureWatchFrom: 5, systemName: 'Capacity A' }, createdByRef: YOU, approvedByRefs: [], changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], approvalsRequired: 2, replaces: 2, createdAt: '2026-10-29T09:00:00Z', effectiveFrom: null }),
    version({ version: 2, status: 'current', values: { pressureWatchFrom: 4, systemName: 'Capacity A' }, approvedByRefs: [SOMEONE_ELSE, THIRD_PERSON], changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], approvalsRequired: 2, replaces: 1, createdAt: '2026-10-20T09:00:00Z', effectiveFrom: '2026-10-21T09:00:00Z' }),
    version({ version: 1, status: 'superseded', values: { systemName: 'Capacity A' }, changedKeys: ['systemName'], clinicalKeys: [], approvalsRequired: 1, replaces: null }),
  ],
};

export const VIEW_VERSIONS = {
  versions: [
    { version: 3, status: 'pending-approval', values: { pressureWatchFrom: 5, systemName: 'Capacity A' }, createdAt: '2026-10-29T09:00:00Z', effectiveFrom: null, reasonCode: '', approvals: 0, approvalsRequired: 2, authoredByYou: true, approvedByYou: false, changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], replaces: 2 },
    { version: 2, status: 'current', values: { pressureWatchFrom: 4, systemName: 'Capacity A' }, createdAt: '2026-10-20T09:00:00Z', effectiveFrom: '2026-10-21T09:00:00Z', reasonCode: '', approvals: 2, approvalsRequired: 2, authoredByYou: false, approvedByYou: false, changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], replaces: 1 },
    { version: 1, status: 'superseded', values: { systemName: 'Capacity A' }, createdAt: '2026-10-10T09:00:00Z', effectiveFrom: '2026-10-11T09:00:00Z', reasonCode: '', approvals: 1, approvalsRequired: 1, authoredByYou: false, approvedByYou: false, changedKeys: ['systemName'], clinicalKeys: [], replaces: null },
  ],
};

export const RAW_LOG = {
  entries: [
    { at: '2026-10-29T10:00:00Z', useCase: 'OpenCrossTenantAccess', action: 'C', role: 'support', actorRef: 'ops-0123456789abcdef0123456789abcdef', entityIds: ['tkt-1', 'acc-1'], snapshot: { ticket: 'tkt-1', by: 'tenant-admin' } },
    { at: '2026-10-28T08:00:00Z', useCase: 'ActivateTenant', action: 'U', role: 'platform-operator', actorRef: 'ops-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', entityIds: [], snapshot: null },
  ],
};

export const VIEW_LOG = {
  entries: [
    { at: '2026-10-29T10:00:00Z', useCase: 'OpenCrossTenantAccess', action: 'C', role: 'support', entityIds: ['tkt-1', 'acc-1'], snapshot: { ticket: 'tkt-1', by: 'tenant-admin' } },
    { at: '2026-10-28T08:00:00Z', useCase: 'ActivateTenant', action: 'U', role: 'platform-operator', entityIds: [], snapshot: null },
  ],
};

function ticket(over: Record<string, unknown>) {
  return {
    id: 'tkt-1',
    state: 'pending',
    requestedByRef: 'ops-0123456789abcdef0123456789abcdef',
    reasonCode: 'service-fault',
    reason: 'The board shows a service twice',
    reference: 'HD-1042',
    requestedAt: '2026-10-30T08:00:00Z',
    validUntil: '2026-10-31T08:00:00Z',
    decidedByRef: null,
    decidedAt: null,
    openedAt: null,
    endedAt: null,
    endedBy: null,
    accessId: null,
    ...over,
  };
}

export const RAW_TICKETS = {
  tickets: [
    ticket({}),
    ticket({ id: 'tkt-2', state: 'approved', decidedByRef: YOU, decidedAt: '2026-10-30T08:30:00Z', reasonCode: 'configuration', reason: 'Check the sender label', reference: null }),
    ticket({ id: 'tkt-3', state: 'opened', decidedByRef: YOU, decidedAt: '2026-10-30T07:00:00Z', openedAt: '2026-10-30T07:10:00Z', accessId: 'acc-3' }),
  ],
};

export const VIEW_TICKETS = {
  tickets: [
    { id: 'tkt-1', state: 'pending', reasonCode: 'service-fault', reason: 'The board shows a service twice', reference: 'HD-1042', requestedAt: '2026-10-30T08:00:00Z', validUntil: '2026-10-31T08:00:00Z', decidedAt: null, openedAt: null, endedAt: null, endedBy: null },
    { id: 'tkt-2', state: 'approved', reasonCode: 'configuration', reason: 'Check the sender label', reference: null, requestedAt: '2026-10-30T08:00:00Z', validUntil: '2026-10-31T08:00:00Z', decidedAt: '2026-10-30T08:30:00Z', openedAt: null, endedAt: null, endedBy: null },
    { id: 'tkt-3', state: 'opened', reasonCode: 'service-fault', reason: 'The board shows a service twice', reference: 'HD-1042', requestedAt: '2026-10-30T08:00:00Z', validUntil: '2026-10-31T08:00:00Z', decidedAt: '2026-10-30T07:00:00Z', openedAt: '2026-10-30T07:10:00Z', endedAt: null, endedBy: null },
  ],
};

export const ONE_TIME_CODE = 'K7R4-92QX';
