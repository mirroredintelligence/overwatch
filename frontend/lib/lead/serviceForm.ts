import { isUkMobile } from '@/lib/forms/ukMobile';

// The add-a-service form (W18, pilot): its values as typed, the checks the form makes before it posts,
// and the JSON it posts to the BFF. A check the back end also makes is repeated here so the lead sees
// it at once; the back end's answer still decides.

export type ServiceValues = {
  name: string;
  category: string | null;
  unitLabel: string;
  measure: string | null;
  establishedCapacity: string;
  usualMin: string;
  usualMax: string;
  cadence: string | null;
  channel: 'text' | 'email';
  mobile: string;
  email: string;
  roleName: string;
  availableFrom: string;
  availableTo: string;
  ageMin: string;
  ageMax: string;
  districts: string;
  accepts: string[];
  excludes: string[];
  reviewBy: string;
};

export type FieldError = { field: string; message: string };

export function blankService(): ServiceValues {
  return {
    name: '',
    category: null,
    unitLabel: '',
    measure: null,
    establishedCapacity: '',
    usualMin: '',
    usualMax: '',
    cadence: null,
    channel: 'text',
    mobile: '',
    email: '',
    roleName: '',
    availableFrom: '',
    availableTo: '',
    ageMin: '',
    ageMax: '',
    districts: '',
    accepts: [],
    excludes: [],
    reviewBy: '',
  };
}

const WHOLE = /^\d+$/;
const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DISTRICT = /^[A-Z]{1,2}[0-9][0-9A-Z]?$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const MOBILE_EXAMPLE = 'Enter a UK mobile number, like 07700 900456';

/** The postcode districts as typed: separated by commas or spaces. */
export function districtsOf(value: string): string[] {
  return value
    .split(/[,\s]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function whole(value: string): number | null {
  return WHOLE.test(value.trim()) ? Number(value.trim()) : null;
}

/** The problems with the form, in the order the form shows them. `now` is epoch ms. */
export function validateService(values: ServiceValues, now: number): FieldError[] {
  const errors: FieldError[] = [];
  const add = (field: string, message: string) => errors.push({ field, message });

  if (values.name.trim() === '') add('lead-add-name', 'Enter the service name');
  if (values.category === null) add('lead-add-category', 'Choose a category');
  if (values.unitLabel.trim() === '') {
    add('lead-add-unit', 'Enter the unit label, for example referrals in the next 2 hrs');
  }
  if (values.measure === null) add('lead-add-measure', 'Choose what is counted');

  const established = whole(values.establishedCapacity);
  if (established === null) add('lead-add-established', 'Enter the established capacity as a whole number');

  const low = whole(values.usualMin);
  const high = whole(values.usualMax);
  if (low === null) add('lead-add-usual-min', 'Enter the lowest usual number as a whole number');
  if (high === null) add('lead-add-usual-max', 'Enter the highest usual number as a whole number');
  else if (low !== null && high < low) {
    add('lead-add-usual-max', 'Highest usual number must be at least the lowest');
  }

  if (values.cadence === null) add('lead-add-cadence', 'Choose how often they report');

  if (values.channel === 'text') {
    if (!isUkMobile(values.mobile)) add('lead-add-mobile', MOBILE_EXAMPLE);
  } else if (!EMAIL.test(values.email.trim())) {
    add('lead-add-email', 'Enter an email address');
  }

  if (values.roleName.trim() === '') add('lead-add-role', 'Enter who holds this phone');
  if (!CLOCK.test(values.availableFrom)) add('lead-add-from', 'Enter the time as HH:MM, like 08:00');
  if (!CLOCK.test(values.availableTo)) add('lead-add-to', 'Enter the time as HH:MM, like 20:00');

  const youngest = whole(values.ageMin);
  if (youngest === null) add('lead-add-age-min', 'Enter the youngest age as a whole number');
  if (values.ageMax.trim() !== '') {
    const oldest = whole(values.ageMax);
    if (oldest === null || (youngest !== null && oldest < youngest)) {
      add('lead-add-age-max', 'Oldest age must be a whole number at least the youngest');
    }
  }

  const districts = districtsOf(values.districts);
  if (districts.length === 0 || districts.some((district) => !DISTRICT.test(district))) {
    add('lead-add-districts', 'Enter a postcode district, like DT4');
  }

  if (values.accepts.length === 0) add('lead-add-accepts', 'Choose at least one need');

  const today = new Date(now).toISOString().slice(0, 10);
  if (!ISO_DATE.test(values.reviewBy) || values.reviewBy <= today) {
    add('lead-add-review', 'Enter a review date in the future');
  }

  return errors;
}

/** The JSON the form posts to the BFF. The phone is sent as typed; the back end normalises it. */
export function toServiceBody(values: ServiceValues): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: values.name.trim(),
    category: values.category,
    measure: values.measure,
    unitLabel: values.unitLabel.trim(),
    establishedCapacity: whole(values.establishedCapacity),
    usualMin: whole(values.usualMin),
    usualMax: whole(values.usualMax),
    cadence: values.cadence,
    channel: values.channel,
    roleName: values.roleName.trim(),
    availableFrom: values.availableFrom,
    availableTo: values.availableTo,
    ageMin: whole(values.ageMin),
    ageMax: values.ageMax.trim() === '' ? null : whole(values.ageMax),
    districts: districtsOf(values.districts),
    accepts: values.accepts,
    excludes: values.excludes,
    reviewBy: values.reviewBy,
  };
  if (values.channel === 'text') body.mobile = values.mobile;
  else body.email = values.email.trim();
  return body;
}
