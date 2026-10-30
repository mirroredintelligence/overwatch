// The chip options of the registration steps, as the screens word them. Each value is the code the
// back end takes (contracts.md and R10); the labels are the screen's own. Pure: the browser and the
// BFF both import it.

export type Option = { value: string; label: string };

export const ORGANISATION_TYPES: readonly Option[] = [
  { value: 'nhs-trust', label: 'NHS trust' },
  { value: 'gp-practice', label: 'GP practice' },
  { value: 'local-authority', label: 'Local authority' },
  { value: 'voluntary-or-independent', label: 'Voluntary or independent' },
  { value: 'other', label: 'Other' },
];
