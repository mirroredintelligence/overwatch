// The words under the map (DEC-1372). Each sentence is there only when the thing it describes is drawn, so a
// map with no patient marker never says "patient shown", and a map with no route never mentions one. Pure.

export type CaptionFacts = {
  /** The patient's area marker is drawn (the location is known). */
  patient: boolean;
  /** At least one visiting service's area is drawn. */
  visiting: boolean;
  /** The route to the selected site is drawn. */
  route: boolean;
  /** The "who covers this area" layer is on. */
  coverage: boolean;
  /** The zoomable map, not the schematic. */
  tiles: boolean;
};

export function captionOf(facts: CaptionFacts): string {
  const parts: string[] = [];
  if (!facts.tiles) parts.push('Schematic, not to scale.');
  if (facts.patient) parts.push("The patient's area is marked at the postcode centre.");
  if (facts.visiting) {
    parts.push(
      facts.coverage
        ? 'Outlined areas are where a visiting service can attend; where two overlap the ground is hatched.'
        : 'Dashed areas are where a visiting service can attend.',
    );
  }
  if (facts.route) parts.push('The dotted line is the route to the selected site.');
  if (facts.tiles) parts.push('Zoom and drag the map to look closer.');
  return parts.join(' ');
}
