import { STALE_AFTER_SECONDS, type OptionsParts, type OptionView } from '@/lib/advisor/options';
import { parseNetworkOptions } from './parse';
import type { NetworkOption, NetworkOptions } from './types';

// The advisor's network options as the cards and the map of the advisor's own options read them (WB11,
// docs/design/network-ui.md section 9). A network row is read only: it names its organisation, has the
// service line to phone and nothing to book, so it is given as an `OptionView` with `network` set, which is
// what turns the booking, "I phoned" and "They declined" controls off on a card. Its reference stands for the
// service where the cards need an id; it is the listing's own opaque one, never a service of an organisation.

export { parseNetworkOptions };

function travelText(low: number, high: number): string {
  return low === high ? `about ${low} min` : `about ${low} to ${high} min`;
}

function viewOf(option: NetworkOption): OptionView {
  const travel = option.travel;
  return {
    serviceId: option.rowRef,
    name: option.serviceName,
    category: option.category,
    status: option.status,
    effectiveAvailable: option.effectiveAvailable,
    overBy: option.overBy,
    unitLabel: option.unitLabel,
    travelText: travel === null ? null : travelText(travel.lowMinutes, travel.highMinutes),
    dataAgeSeconds: option.dataAgeSeconds,
    staleWarning: option.dataAgeSeconds !== null && option.dataAgeSeconds > STALE_AFTER_SECONDS,
    // Another organisation's service: its reporting times are not shared, only the figure and its age.
    reportedAt: null,
    nextDueAt: null,
    cadence: null,
    lastFigure: null,
    overdue: false,
    figureUnavailable:
      option.status === 'not-updated' ||
      (option.dataAgeSeconds !== null && option.dataAgeSeconds > STALE_AFTER_SECONDS),
    criteriaVersion: option.criteriaVersion,
    fits: option.fits,
    checks: option.warnings,
    phone: option.contactPhone,
    network: { organisation: option.organisationName, source: '' },
    position: option.position,
    coverage: null,
    travel: travel === null ? null : { low: travel.lowMinutes, high: travel.highMinutes, source: '', legs: [] },
  };
}

export function networkOptionsToParts(answer: NetworkOptions): OptionsParts {
  return {
    options: answer.options.map(viewOf),
    notSuitable: answer.notSuitable.map((row) => ({ serviceId: row.rowRef, name: row.serviceName, reason: row.reason, organisation: row.organisationName })),
    patientArea: answer.patient,
    notFound: answer.notFound,
    outOfArea: answer.outOfArea,
    // The case's own district chips are the tenant's list: the network variant offers none.
    districts: [],
  };
}
