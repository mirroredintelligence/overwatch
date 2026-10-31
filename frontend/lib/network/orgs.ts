// The organisations of a network view (TEN-069, TEN-070): a list for the filter chips, and whether a row is
// the viewer's own. A network row names its organisation by display name only, so each gets an opaque
// reference (`org-1`...) for the page to tell chips apart by: neither the name nor an id is an attribute.

export type Organisation = { ref: string; name: string; own: boolean };

/** True for the viewer's own organisation: the display name from its profile equals the row's. */
export function ownRow(organisationName: string, ownOrganisation: string | null): boolean {
  return ownOrganisation !== null && organisationName === ownOrganisation;
}

/** Each organisation once: the viewer's own first, then the others alphabetically. */
export function organisationsOf(names: readonly string[], ownOrganisation: string | null): Organisation[] {
  const unique = [...new Set(names)].sort((a, b) => a.localeCompare(b, 'en-GB'));
  const own = unique.filter((name) => ownRow(name, ownOrganisation));
  const others = unique.filter((name) => !ownRow(name, ownOrganisation));
  return [...own, ...others].map((name, index) => ({ ref: `org-${index + 1}`, name, own: ownRow(name, ownOrganisation) }));
}
