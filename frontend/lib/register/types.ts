// Shared registration types (W54 to W27). The browser sees only these shapes; the BFF answers with
// them and nothing else from the back end.

export const STEP_NAMES = ['organisation', 'location', 'service', 'reporting', 'api'] as const;
export type StepName = (typeof STEP_NAMES)[number];

export const REGISTRATION_STATUSES = [
  'invited',
  'draft',
  'submitted',
  'in-review',
  'needs-changes',
  'approved',
  'live',
  'not-approved',
  'paused',
  'reverify',
] as const;
export type RegistrationStatus = (typeof REGISTRATION_STATUSES)[number];

/** The saved answers of one step, as the back end holds them, for prefilling a form. */
export type StepValues = Record<string, string | number | boolean | null | undefined>;

/**
 * The registration as the applicant's pages see it (DEC-904): its status, the service the registration
 * is for (set by the lead, so locked on every step) and the saved steps. The organisation's name and
 * ODS code are typed by the applicant (DEC-910), so they are saved answers, not locked invitation values.
 */
export type RegistrationView = {
  id: string;
  status: RegistrationStatus;
  serviceName: string;
  steps: Partial<Record<StepName, StepValues>>;
};

/** One problem with one field, in the words the page shows. `field` is the element id it links to. */
export type FieldIssue = { field: string; message: string };
