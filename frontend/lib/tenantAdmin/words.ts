// The words the tenant administration and the operator console print for what the back end names in codes.
// Pure text, no tenant, nothing clinical of its own. A code this module does not know is printed as it is:
// it is never guessed at. Every clock time is London time, as the lead's pages say it (DEC-151).

import type { SettingJson, SettingSpec } from './views';

const when = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/London',
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** "21 Oct 2026, 10:00" in London time, or a dash for no time. */
export function whenText(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) return '-';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '-';
  return when.format(date).replace(/,? (?=\d{2}:\d{2}$)/, ', ');
}

/** "pressureWatchFrom" as "Pressure watch from". */
export function humaniseKey(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A setting's value as a person reads it: with its unit when it has one, a list in order, an absent one as "not set". */
export function valueText(spec: Pick<SettingSpec, 'kind' | 'unit'>, value: SettingJson | null | undefined): string {
  if (value === undefined || value === null) return 'not set';
  if (Array.isArray(value)) return value.length === 0 ? 'none' : value.join(', ');
  if (typeof value === 'boolean') return value ? 'on' : 'off';
  if (spec.kind === 'int' && spec.unit !== 'count') return `${value} ${spec.unit}`;
  return String(value);
}

const ROLES: Record<string, string> = { 'platform-operator': 'Platform operator', support: 'Support' };

export function roleWord(role: string): string {
  return ROLES[role] ?? role;
}

const STATES: Record<string, string> = {
  pending: 'Waiting for you',
  approved: 'Approved, code not used yet',
  refused: 'Refused',
  cancelled: 'Cancelled by the support person',
  opened: 'Open now',
  ended: 'Ended',
  revoked: 'Taken back',
  expired: 'Lapsed',
};

/** A ticket's state from the administrator's side. */
export function stateWord(state: string): string {
  return STATES[state] ?? state;
}

const ACTIONS: Record<string, string> = {
  CreateTenant: 'Created your organisation',
  RecordTenantNumber: 'Recorded a text number',
  MarkNumberTested: 'Marked a text number as tested',
  SetTenantHost: 'Set the address of your service',
  RecordTenantReferences: 'Recorded your agreement references',
  VerifyEntraBinding: 'Verified your directory',
  ActivateTenant: 'Activated your organisation',
  InviteTenantAdmin: 'Invited your first administrator',
  SuspendTenant: 'Suspended your organisation',
  ResumeTenant: 'Resumed your organisation',
  StartTenantOffboarding: 'Started closing your organisation',
  OpenCrossTenantAccess: 'Opened access with a support code',
  UseCrossTenantAccess: 'Used a support access',
  EndCrossTenantAccess: 'Ended a support access',
  RevokeCrossTenantAccess: 'Took back a support access',
  SupportAccessTicket: 'Recorded a step on a support request',
};

/** What a platform step was, in plain words. */
export function plainAction(useCase: string): string {
  return ACTIONS[useCase] ?? useCase;
}

const REASONS: Record<string, string> = {
  'security-incident': 'Security incident',
  'clinical-safety': 'Clinical safety',
  'service-fault': 'Service fault',
  configuration: 'Configuration',
  'user-request': 'A user asked for help',
  other: 'Other',
};

export function reasonWord(code: string): string {
  return REASONS[code] ?? code;
}

export const REASON_OPTIONS: readonly [string, string][] = Object.entries(REASONS);
