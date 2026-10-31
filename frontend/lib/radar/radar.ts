import type { OptionView } from '@/lib/advisor/options';
import type { LatLon } from '@/lib/map/project';
import { covers, overlaps } from './geometry';

// What the radar screens draw and say, worked out from the case's options (RadarWeb, RadarPhone). The
// options are the ones the back end already sends for the map (`$filter-options`); nothing here is
// read from anywhere else, and nothing ranks a service (the options are listed, not scored). Pure.

/** The category the back end gives hospital at home and virtual wards: the remote lane, and its own layer. */
export const HOME_CATEGORY = 'hospital-at-home-or-virtual-ward';

/** The three ways to meet the need (RadarWeb 6): someone comes, the patient stays, or the patient goes. */
export type Lane = 'comes' | 'remote' | 'place';

export const LANE_TEXT: Record<Lane, { title: string; hint: string }> = {
  comes: { title: 'Comes to the patient', hint: 'Someone visits' },
  remote: { title: 'Remote', hint: 'The patient stays where they are' },
  place: { title: 'Goes to a place', hint: 'Needs transport' },
};

/** Which lane a service is in: a virtual service is remote, a visiting one comes, anything else is a place. */
export function laneOf(option: OptionView): Lane {
  if (option.category === HOME_CATEGORY) return 'remote';
  if (option.coverage !== null) return 'comes';
  return 'place';
}

export function groupByLane(options: readonly OptionView[]): Record<Lane, OptionView[]> {
  const lanes: Record<Lane, OptionView[]> = { comes: [], remote: [], place: [] };
  for (const option of options) lanes[laneOf(option)].push(option);
  return lanes;
}

/** "Can the patient travel?" (RadarWeb 6, RadarPhone 5). Optional: no answer keeps the default order. */
export type CanTravel = 'yes' | 'help' | 'no';

export const CAN_TRAVEL: readonly { value: CanTravel; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'help', label: 'With help' },
  { value: 'no', label: 'No' },
];

/**
 * The order the lanes are shown in. The answer only changes the order, never what is listed: a patient
 * who can travel sees the places first; one who cannot sees the lanes that come or stay, then the places.
 */
export function laneOrder(canTravel: CanTravel | null): Lane[] {
  if (canTravel === 'yes') return ['place', 'comes', 'remote'];
  if (canTravel === 'help') return ['comes', 'place', 'remote'];
  return ['comes', 'remote', 'place'];
}

/** The layers of the radar map the advisor can turn on and off. */
export type Layer = 'visiting' | 'home' | 'places';

export const LAYERS: readonly { id: Layer; label: string }[] = [
  { id: 'visiting', label: 'Visiting services' },
  { id: 'home', label: 'Hospital at home' },
  { id: 'places', label: 'Places to go' },
];

/** The services a layer draws. */
export function inLayer(option: OptionView, layer: Layer): boolean {
  if (layer === 'places') return option.position !== null;
  const isHome = option.category === HOME_CATEGORY;
  if (layer === 'home') return option.coverage !== null && isHome;
  return option.coverage !== null && !isHome;
}

/** Every visiting service in the list, with its area. */
export function visitingOf(options: readonly OptionView[]): OptionView[] {
  return options.filter((option) => option.coverage !== null);
}

/** The visiting services whose area includes the patient's point. */
export function coveringPatient(options: readonly OptionView[], patient: LatLon | null): OptionView[] {
  if (patient === null) return [];
  return visitingOf(options).filter((option) => option.coverage !== null && covers(option.coverage, patient));
}

/** The pairs of visiting services whose areas share ground (drawn hatched). */
export function overlappingPairs(options: readonly OptionView[]): [OptionView, OptionView][] {
  const visiting = visitingOf(options);
  const pairs: [OptionView, OptionView][] = [];
  visiting.forEach((first, index) => {
    for (const second of visiting.slice(index + 1)) {
      if (first.coverage !== null && second.coverage !== null && overlaps(first.coverage, second.coverage)) {
        pairs.push([first, second]);
      }
    }
  });
  return pairs;
}

/** The one-line summary under the map (RadarWeb 1). */
export function coverSummary(covering: readonly OptionView[]): string {
  const count = covering.length;
  if (count === 0) return 'No visiting service covers this patient area. Places to go are still listed.';
  const head = `This patient is covered by ${count} ${count === 1 ? 'service' : 'services'}.`;
  return count === 1 ? head : `${head} Their areas overlap here, so compare them.`;
}

/** The services the compare screen lines up: those that come to the patient or stay remote. */
export function comparable(options: readonly OptionView[]): OptionView[] {
  return options.filter((option) => laneOf(option) !== 'place');
}
