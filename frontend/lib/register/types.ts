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

/** What the invitation fixes. These are read-only on every step: the BFF takes them from the back end, never from the browser. */
export type Invitation = {
  serviceName: string;
  organisationName: string;
  odsCode: string;
};

/** The saved answers of one step, as the back end holds them, for prefilling a form. */
export type StepValues = Record<string, string | number | boolean | null | undefined>;

export type RegistrationView = {
  id: string;
  status: RegistrationStatus;
  invitation: Invitation;
  steps: Partial<Record<StepName, StepValues>>;
};

/** One problem with one field, in the words the page shows. `field` is the element id it links to. */
export type FieldIssue = { field: string; message: string };
