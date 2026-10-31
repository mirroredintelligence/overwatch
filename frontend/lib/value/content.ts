// The value case's words (ValueCase artboard, docs/spec/ui-screens.md). What is promised to each group,
// and what is measured to prove it. No saving is stated as a fact here: every target is "[to agree]" until
// the baseline is measured, and the rules for claiming savings say so. No deployment name is used: the
// artboard's name for the coordination team is replaced by "coordination team" (as in the product tour).

export type Pledge = { group: string; items: readonly string[] };

export const PROMISES: readonly Pledge[] = [
  {
    group: 'Services',
    items: ['One tap or one text, about 10 seconds', 'Fewer phone calls to the ward', 'Nobody chases you'],
  },
  {
    group: 'Call advisors and shift leads',
    items: ['See what is open and how old it is', 'Request by text and move on', 'Chasing late reporters is automatic'],
  },
  {
    group: 'Clinical advisors',
    items: ['Requests arrive with the case ready', 'Advice on one screen, logged'],
  },
  {
    group: 'COOs and ICB',
    items: ['System picture on your phone', 'Alerts only for what you choose', 'A weekly summary replaces a meeting'],
  },
];

export const TARGET_PLACEHOLDER = '[to agree]';

export type Measure = { measure: string; baseline: string; after: string; target: string };

export const MEASURES: readonly Measure[] = [
  {
    measure: 'Phone calls to services per shift (coordination team)',
    baseline: 'Count on a sample of shifts, 2 weeks before go-live',
    after: 'Calls logged by reason: confirm capacity, confirm booking',
    target: TARGET_PLACEHOLDER,
  },
  {
    measure: 'Time from request to a confirmed place',
    baseline: 'Stopwatch on a sample of calls',
    after: 'Request sent to CONFIRMED, in minutes',
    target: TARGET_PLACEHOLDER,
  },
  {
    measure: 'Age of the capacity figure at the moment of a decision',
    baseline: 'Unknown today',
    after: 'Saved with every decision',
    target: TARGET_PLACEHOLDER,
  },
  {
    measure: 'Capacity updates on time',
    baseline: 'Not measured today',
    after: 'Updates received by the due time, per service',
    target: TARGET_PLACEHOLDER,
  },
  {
    measure: 'Meetings and huddles about capacity per week',
    baseline: 'Ask leads, check calendars',
    after: 'Same count after go-live, from calendars',
    target: TARGET_PLACEHOLDER,
  },
  {
    measure: 'Referrals declined despite showing capacity',
    baseline: 'Not measured today',
    after: 'Logged by service and hour',
    target: TARGET_PLACEHOLDER,
  },
];

export const SAVINGS_RULES =
  'No saving is claimed before the baseline is measured. Every estimate is labelled as an estimate and shows its sum. Show a range, not one number. The first week summary for each person reports real counts, such as updates sent, and says how the avoided-call figure is worked out.';

export type LaunchItem = { text: string; href?: string };

export const LAUNCH_KIT: readonly LaunchItem[] = [
  { text: 'A one-minute product tour by role', href: '/tour' },
  { text: 'Two-minute lessons with a practice mode', href: '/learn' },
  { text: 'One champion per service and per shift' },
  { text: 'A one-page quick guide' },
  { text: 'A Friday summary of what each person saved' },
];
