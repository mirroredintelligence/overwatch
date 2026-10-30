// The reports the rules flag (W42). The screen says each rule in words; a reason the screen does not know
// is still shown, as "Flagged by rules.", so a flag is never hidden (DEC-658).

const SUMMARIES: Record<string, string> = {
  'out-of-range-twice': 'The figure was out of its usual range twice.',
  'many-changes': 'The figure changed many times in a short time.',
  'differs-from-phoned': 'The figure differs from what advisors recorded by phone.',
};

export type FlagItem = {
  id: string;
  serviceId: string;
  serviceName: string;
  reason: string;
  summary: string;
};

export function flagSummary(reason: string): string {
  return SUMMARIES[reason] ?? 'Flagged by rules.';
}

type Bundle = { entry?: { resource?: Record<string, unknown> }[] };

/** The open flags of a back-end Bundle, as the screen shows them. An entry with no id or no service is dropped. */
export function flagItemsFrom(bundle: unknown): FlagItem[] {
  const entries = (bundle as Bundle | undefined)?.entry ?? [];
  const items: FlagItem[] = [];
  for (const entry of entries) {
    const resource = entry.resource;
    if (resource?.resourceType !== 'Flag' || typeof resource.id !== 'string') continue;
    const subject = resource.subject as { reference?: unknown; display?: unknown } | undefined;
    const reference = typeof subject?.reference === 'string' ? subject.reference : '';
    if (!reference.startsWith('HealthcareService/')) continue;
    const serviceId = reference.slice('HealthcareService/'.length);
    const coding = (resource.code as { coding?: { code?: unknown }[] } | undefined)?.coding ?? [];
    const code = typeof coding[0]?.code === 'string' ? coding[0].code : 'unknown';
    const reason = code in SUMMARIES ? code : 'unknown';
    items.push({
      id: resource.id,
      serviceId,
      serviceName: typeof subject?.display === 'string' ? subject.display : serviceId,
      reason,
      summary: flagSummary(reason),
    });
  }
  return items;
}
