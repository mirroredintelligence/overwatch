import type { Scope } from './views';

// The words for what leaves an organisation for a network (TEN-081, docs/design/network-ui.md section 8,
// "Field labels"). Keyed by the DTO field names of `domain/rules/projection.py`, which the back end's sharing
// read lists (`allowlist`). A field the back end sends that has no group here cannot be described, so the
// screen says it cannot list it (fail closed) and the test fails; a group whose fields the back end no longer
// sends is never shown. A group with no label is an internal reference: it is never listed on the screen.
// Pure text and no import of the server: safe for the browser.

export type FieldGroup = { label: string | null; fields: readonly string[] };

export const FIELD_LABELS: Readonly<Record<Scope, readonly FieldGroup[]>> = {
  directory: [
    { label: 'Service name', fields: ['service_name'] },
    { label: 'Service category', fields: ['category'] },
    { label: 'Whether the service is active', fields: ['active'] },
    { label: 'Where the entry came from', fields: ['source'] },
    { label: 'Service line name and number', fields: ['contact_label', 'contact_phone'] },
    { label: 'Location name and town or city', fields: ['location_name', 'city'] },
    { label: 'Postcode district only (for example DT4)', fields: ['postal_district'] },
    { label: 'Map position of the location', fields: ['latitude', 'longitude'] },
    { label: 'Opening hours', fields: ['opening_hours'] },
    { label: null, fields: ['source_service_id', 'source_version'] },
  ],
  capacity: [
    { label: 'What the figure counts and its unit', fields: ['measure', 'unit_label'] },
    { label: 'Established capacity', fields: ['established_capacity'] },
    { label: 'Whether the service can go over established capacity', fields: ['can_exceed_established'] },
    { label: 'Level at which the service shows as Limited', fields: ['limited_level_percent'] },
    { label: 'How often the service reports', fields: ['cadence'] },
    { label: 'Whether the service is suspended', fields: ['suspended'] },
    { label: 'The latest reported figure and when it was reported', fields: ['value', 'reported_at'] },
    { label: 'How many bookings were confirmed since that report (a count, never the bookings)', fields: ['confirmed_since'] },
    { label: 'How long a reply is expected, and when the figure counts as old', fields: ['reply_window_minutes', 'stale_warning_hours'] },
    { label: null, fields: ['source_service_id', 'source_version', 'report_id', 'valid_until'] },
  ],
  criteria: [
    { label: 'Age range', fields: ['age_min', 'age_max'] },
    { label: 'Postcode districts', fields: ['districts'] },
    { label: 'Needs accepted and needs excluded', fields: ['accepts', 'excludes'] },
    { label: 'Review-by date', fields: ['review_by'] },
    { label: 'Current version number', fields: ['version'] },
    { label: null, fields: ['source_criteria_id', 'source_service_id'] },
  ],
};

/** The fields the back end sends with no group, and the labels none of whose fields it sends. */
export function checkLabels(scope: Scope, fields: readonly string[]): { unlabelled: string[]; unused: string[] } {
  const known = new Set(FIELD_LABELS[scope].flatMap((group) => group.fields));
  const sent = new Set(fields);
  return {
    unlabelled: fields.filter((field) => !known.has(field)),
    unused: FIELD_LABELS[scope].filter((group) => group.label !== null && !group.fields.some((field) => sent.has(field))).map((group) => group.label as string),
  };
}

/** The sentences for what is sent, in the table's order, with the internal references left out. */
export function labelsFor(scope: Scope, fields: readonly string[]): string[] {
  const sent = new Set(fields);
  return FIELD_LABELS[scope]
    .filter((group) => group.label !== null && group.fields.some((field) => sent.has(field)))
    .map((group) => group.label as string);
}

export const NEVER_SHARED =
  "Never shared: reporters' names, phone numbers, devices and PINs; links and codes; messages sent or received; bookings and cases; audit entries; anything about a patient.";
