// The product tour's words (W52). Copied from the TourPhone1 and TourRoles artboards in
// docs/spec/ui-screens.md. A saving is never stated as a fact here: the reporter screen says
// "[x] minutes" until the pilot measures it (ValueCase, "Rules for claiming savings").

export const TOUR_ROLES = ['reporter', 'advisor', 'lead', 'clinical', 'exec'] as const;
export type TourRole = (typeof TOUR_ROLES)[number];

export const ROLE_CHOICES: Record<TourRole, string> = {
  reporter: 'I report capacity for a service',
  advisor: 'I take calls as an advisor',
  lead: 'I am a shift lead',
  clinical: 'I am a clinical advisor',
  exec: 'I am a COO or ICB lead',
};

export type RoleScreen = {
  heading: string;
  today: readonly string[];
  withDiucs: readonly string[];
  action: string;
  /** A closing line for the role, when the artboard has one. */
  closing?: string;
};

export const ROLE_SCREENS: Record<TourRole, RoleScreen> = {
  reporter: {
    heading: 'Your day, before and after',
    today: [
      'Phone calls from the coordination team asking for beds',
      'Whiteboards and emails at set times',
      'Chased when a report is late',
    ],
    withDiucs: ['We ask. You tap. About 10 seconds.', 'The board is current, so fewer calls', 'Nobody chases you'],
    action: 'Try a practice update',
    closing: 'A phone call today takes [x] minutes. We measure it in the pilot.',
  },
  advisor: {
    heading: 'For call advisors',
    today: [
      'Phone several services to find space',
      'Check whiteboards and emails that may be hours old',
      'Key the same details into each referral',
    ],
    withDiucs: [
      'See what is open, and how old each figure is',
      'Request a booking by text and move on',
      'Copy one summary into SystmOne',
    ],
    action: 'Try a practice call',
  },
  lead: {
    heading: 'For shift leads',
    today: ['Chase late reporters by phone', 'Keep a list of who covers whom', 'Hold catch-up meetings to find the picture'],
    withDiucs: [
      'See who has not reported and chase in one tap',
      'Change a cover number in seconds',
      'Everyone sees the same board, so fewer huddles',
    ],
    action: 'Invite a reporter',
  },
  clinical: {
    heading: 'For clinical advisors',
    today: ['Interrupted by calls with no case ready', 'Asked the same questions again'],
    withDiucs: ['Requests arrive with the case and what the advisor saw', 'Advise on one screen and it is logged'],
    action: 'Go on duty',
  },
  exec: {
    heading: 'For COOs and ICB leads',
    today: ['Ask for updates by phone and in meetings', 'Hear about pressure late', 'Cannot see unused capacity'],
    withDiucs: ['The system picture in your pocket', 'Alerts only for what you choose', 'A weekly summary replaces a meeting'],
    action: 'Choose my alerts',
  },
};

export const HOW_IT_WORKS = [
  { title: 'We ask', body: 'A notification arrives at your usual time' },
  { title: 'You tap', body: 'Yes, still right. Or send a new number.' },
  { title: 'The coordination team sees it at once', body: 'The board updates. No call needed.' },
] as const;

export const FIRST_WEEK = [
  'Set up your phone',
  'Reply to your first prompt',
  'Add a cover number',
  'Have a look at the live board',
] as const;

export const FIRST_WEEK_NOTE = 'On Friday we show you what you saved: updates sent and phone calls avoided.';
