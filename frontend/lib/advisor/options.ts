import type { StatusCode } from '@/components/ui/StatusBadge';

// The options of a case as the browser reads them (W13): the back end's `$filter-options` Parameters
// (routes_cases.py `_filter_to_fhir`) turned into plain data. Pure. Only the parts named here are
// read; anything else in the answer is dropped, so no field the browser does not show can reach it.
// A status the rules do not know is shown as Not updated, never as accepting.

/** Data older than this is flagged: "Data is over 2 hrs old. Consider phoning." (W13). */
export const STALE_AFTER_SECONDS = 2 * 60 * 60;

const KNOWN_STATUS: readonly StatusCode[] = [
  'accepting',
  'limited',
  'not-accepting',
  'over-capacity',
  'not-updated',
  'out-of-hours',
];

/** The organisation that owns a network service, and where its figures come from (network-ui.md). */
export type NetworkTag = { organisation: string; source: string };

export type OptionView = {
  serviceId: string;
  name: string;
  category: string | null;
  status: StatusCode;
  effectiveAvailable: number | null;
  overBy: number | null;
  unitLabel: string | null;
  travelText: string | null;
  dataAgeSeconds: number | null;
  staleWarning: boolean;
  criteriaVersion: number | null;
  fits: string[];
  checks: string[];
  phone: string | null;
  /** Null for the viewer's own organisation. */
  network: NetworkTag | null;
};

export type NotSuitableView = { serviceId: string; name: string; reason: string };

export type OptionsParts = { options: OptionView[]; notSuitable: NotSuitableView[] };

type Part = { name?: unknown; valueString?: unknown; valueCode?: unknown; valueInteger?: unknown; part?: unknown };

const asParts = (value: unknown): Part[] => (Array.isArray(value) ? (value as Part[]) : []);

function text(parts: Part[], name: string): string | null {
  const found = parts.find((part) => part.name === name);
  if (typeof found?.valueString === 'string') return found.valueString;
  if (typeof found?.valueCode === 'string') return found.valueCode;
  return null;
}

function whole(parts: Part[], name: string): number | null {
  const found = parts.find((part) => part.name === name);
  return typeof found?.valueInteger === 'number' && Number.isInteger(found.valueInteger) ? found.valueInteger : null;
}

function list(parts: Part[], name: string): string[] {
  return parts
    .filter((part) => part.name === name && typeof part.valueString === 'string')
    .map((part) => part.valueString as string);
}

function travelText(low: number | null, high: number | null): string | null {
  if (low === null || high === null) return null;
  return low === high ? `about ${low} min` : `about ${low} to ${high} min`;
}

function optionOf(parts: Part[]): OptionView | null {
  const serviceId = text(parts, 'serviceId');
  const name = text(parts, 'name');
  if (serviceId === null || name === null) return null;
  const rawStatus = text(parts, 'status');
  const status: StatusCode =
    rawStatus !== null && (KNOWN_STATUS as readonly string[]).includes(rawStatus)
      ? (rawStatus as StatusCode)
      : 'not-updated';
  const dataAgeSeconds = whole(parts, 'dataAgeSeconds');
  return {
    serviceId,
    name,
    category: text(parts, 'category'),
    status,
    effectiveAvailable: whole(parts, 'effectiveAvailable'),
    overBy: whole(parts, 'overBy'),
    unitLabel: text(parts, 'unitLabel'),
    travelText: travelText(whole(parts, 'travelLow'), whole(parts, 'travelHigh')),
    dataAgeSeconds,
    staleWarning: dataAgeSeconds !== null && dataAgeSeconds > STALE_AFTER_SECONDS,
    criteriaVersion: whole(parts, 'criteriaVersion'),
    fits: list(parts, 'fits'),
    checks: list(parts, 'checks'),
    phone: null,
    network: null,
  };
}

/**
 * The options and the not-suitable list, in the order the back end sent them. Null when the answer
 * is not a Parameters resource, so the route can answer 502 rather than show a guess.
 */
export function optionsFromParameters(value: unknown): OptionsParts | null {
  if (typeof value !== 'object' || value === null) return null;
  const resource = value as { resourceType?: unknown; parameter?: unknown };
  if (resource.resourceType !== 'Parameters') return null;

  const options: OptionView[] = [];
  const notSuitable: NotSuitableView[] = [];
  for (const item of asParts(resource.parameter)) {
    const parts = asParts(item.part);
    if (item.name === 'option') {
      const option = optionOf(parts);
      if (option !== null) options.push(option);
    } else if (item.name === 'notSuitable') {
      const serviceId = text(parts, 'serviceId');
      const name = text(parts, 'name');
      const reason = text(parts, 'reason');
      if (serviceId !== null && name !== null && reason !== null) notSuitable.push({ serviceId, name, reason });
    }
  }
  return { options, notSuitable };
}
