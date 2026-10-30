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

export const SERVICE_CATEGORIES: readonly Option[] = [
  { value: 'urgent-community-response', label: 'Urgent community response' },
  { value: 'same-day-emergency-care', label: 'Same day emergency care' },
  { value: 'inpatient-beds', label: 'Inpatient beds' },
  { value: 'hospital-at-home-or-virtual-ward', label: 'Hospital at home or virtual ward' },
  { value: 'reablement', label: 'Reablement' },
  { value: 'urgent-treatment', label: 'Urgent treatment' },
  { value: 'mental-health-crisis', label: 'Mental health crisis' },
  { value: 'other', label: 'Other' },
];

export const REFERRAL_METHODS: readonly Option[] = [
  { value: 'phone', label: 'Phone' },
  { value: 'systmone', label: 'SystmOne' },
  { value: 'email', label: 'Email' },
  { value: 'e-referral', label: 'e-Referral' },
];

export const DAY_OPTIONS: readonly Option[] = [
  { value: 'mon', label: 'Mon' },
  { value: 'tue', label: 'Tue' },
  { value: 'wed', label: 'Wed' },
  { value: 'thu', label: 'Thu' },
  { value: 'fri', label: 'Fri' },
  { value: 'sat', label: 'Sat' },
  { value: 'sun', label: 'Sun' },
];

/** The needs a service accepts (the back end's NeedCategory codes). */
export const NEED_OPTIONS: readonly Option[] = [
  { value: 'fall-no-injury', label: 'Fall, no injury' },
  { value: 'frailty', label: 'Frailty' },
  { value: 'wound-care', label: 'Wound care' },
  { value: 'iv-therapy', label: 'IV therapy' },
  { value: 'palliative', label: 'Palliative' },
  { value: 'dementia', label: 'Dementia' },
];

/** The needs a service does not accept. "Needs IV therapy" is the same code as the accepted need. */
export const EXCLUDED_NEED_OPTIONS: readonly Option[] = [
  { value: 'suspected-fracture', label: 'Suspected fracture' },
  { value: 'head-injury-anticoagulants', label: 'Head injury on anticoagulants' },
  { value: 'iv-therapy', label: 'Needs IV therapy' },
  { value: 'infection-isolation', label: 'Infection isolation' },
];

export const NO_EXCLUSIONS = 'no-exclusions';

/** What the applicant counts. The chip value is the screen's; reporting.ts sends the measure code. */
export const COUNT_OPTIONS: readonly Option[] = [
  { value: 'referrals', label: 'Referrals in the next 2 hrs' },
  { value: 'beds', label: 'Beds free' },
  { value: 'slots', label: 'Slots left today' },
  { value: 'packages', label: 'Packages available' },
  { value: 'virtual-beds', label: 'Virtual beds free' },
  { value: 'other', label: 'Other' },
];

export const CADENCE_OPTIONS: readonly Option[] = [
  { value: 'every-2-hrs', label: 'Every 2 hrs' },
  { value: 'twice-a-day', label: 'Twice a day' },
  { value: 'once-a-day', label: 'Once a day' },
];

export const CHANNEL_OPTIONS: readonly Option[] = [
  { value: 'push', label: 'App notification' },
  { value: 'text', label: 'Text' },
  { value: 'email', label: 'Email' },
];
