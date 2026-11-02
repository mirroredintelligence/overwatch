import type { parseConsent, parseTenantDetail } from './views';
import { NHS_ORGANISATION_TYPE_CODES } from './words';

// The "Go live" funnel of a partner organisation's page: the steps in order, whether each is done, which one is next,
// and what the back end's activation blockers mean in plain words and for which step. Derived only from the tenant
// detail and the consent invitation the page already reads; nothing here writes.

type Detail = ReturnType<typeof parseTenantDetail>;
export type Consent = ReturnType<typeof parseConsent>;
export type ConsentRead = { status: 'loading' } | { status: 'ok'; data: Consent } | { status: 'failed'; http: number };

export const STEP_IDS = ['organisation', 'signin', 'invite', 'team', 'roles', 'reach', 'agreements', 'golive'] as const;
export type StepId = (typeof STEP_IDS)[number];

export const STEP_TITLES: Record<StepId, string> = {
  organisation: 'Confirm the organisation',
  signin: 'Connect their sign-in',
  invite: 'Invite their administrator',
  team: 'Set up their administrators’ team',
  roles: 'Who can do what',
  reach: 'How people reach them',
  agreements: 'Agreements',
  golive: 'Go live',
};

/** The teams people can be put in, with what each can do, in plain words. [role code, team name, what it can do]. */
export const TEAM_WORDS: readonly [string, string, string][] = [
  ['advisor', 'Advisors', 'Look up which services can take a patient right now and book them in.'],
  ['lead', 'Shift leads', 'Run the board for a shift and keep service figures up to date.'],
  ['clinical', 'Clinical leads', 'Review clinical safety and decide the rules for what is safe.'],
  ['exec', 'Planning', 'See the pressure across the area over time to plan ahead.'],
  ['audit', 'Audit', 'Read the record of who did what. They cannot change anything.'],
  ['owner', 'Criteria owners', 'Own the rules that decide which services suit which patients.'],
];

export function teamName(code: string): string {
  if (code === 'tenant-admin') return 'Administrators';
  return TEAM_WORDS.find(([value]) => value === code)?.[1] ?? 'A team';
}

type Missing = { step: StepId; words: string };

const BY_THEM = 'Their administrators set this in Overwatch once they sign in';

/** What each of the back end's activation blockers means, in words, and the step it belongs to. */
function describeBlocker(blocker: string): Missing {
  const text = blocker.toLowerCase();
  if (text.includes('host')) return { step: 'reach', words: 'The web address is not set.' };
  if (text.includes('number') || text.includes('test text')) return { step: 'reach', words: 'A text number has not been tested yet.' };
  if (text.includes('time zone')) return { step: 'organisation', words: 'The time zone is not set.' };
  if (text.includes('directory')) return { step: 'signin', words: 'Their Microsoft work accounts are not connected and confirmed yet.' };
  if (text.includes('email')) return { step: 'invite', words: 'Overwatch cannot send email for this organisation yet. Tell the Overwatch team.' };
  if (text.includes('administrator group')) return { step: 'team', words: 'Their administrators’ team is not set up yet.' };
  if (text.includes('role mapping')) return { step: 'roles', words: 'No team has been given anything to do yet.' };
  if (text.includes('references')) return { step: 'agreements', words: 'The agreements are not all recorded yet.' };
  if (text.includes('network agreement')) return { step: 'golive', words: 'Their administrator has not accepted the network agreement yet.' };
  if (text.includes('contacts')) return { step: 'golive', words: `The support contacts are not set. ${BY_THEM}.` };
  if (text.includes('retention')) return { step: 'golive', words: `How long records are kept is not set. ${BY_THEM}.` };
  if (text.includes('districts')) return { step: 'golive', words: `The area’s districts are not set. ${BY_THEM}.` };
  if (text.includes('names set') || text.includes('wording')) return { step: 'golive', words: `The names they use for their systems are not set. ${BY_THEM}.` };
  if (text.includes('configuration')) return { step: 'golive', words: `Their settings have not been approved yet. ${BY_THEM}.` };
  return { step: 'golive', words: 'Something else still has to be finished. Tell the Overwatch team.' };
}

export type FunnelStep = { id: StepId; number: number; title: string; done: boolean; missing: string[] };

export type Funnel = {
  steps: FunnelStep[];
  /** The step the operator should do next (the first that is not done). Null when every step is done. */
  next: StepId | null;
  doneCount: number;
  total: number;
  /** Every step before Go live is done and the back end agrees. Only then is the Go live button shown. */
  canGoLive: boolean;
  /** Everything still missing, in plain words, with the step it belongs to. */
  missing: Missing[];
};

export function deriveFunnel(detail: Detail, consent: ConsentRead): Funnel {
  const t = detail.tenant;
  const verified = detail.bindings.some((b) => b.status === 'verified');
  const consented = consent.status === 'ok' && consent.data.invitation?.status === 'consented';
  const mapped = detail.roleMappings.filter((m) => m.status === 'active');
  const hasAdminTeam = mapped.some((m) => m.role === 'tenant-admin');
  const hasOtherTeam = mapped.some((m) => m.role !== 'tenant-admin');
  const refs = t.references;

  const missing: Missing[] = [];
  const need = (step: StepId, words: string, ok: boolean) => {
    if (!ok) missing.push({ step, words });
  };
  const nhs = NHS_ORGANISATION_TYPE_CODES.includes(t.organisationType);
  need('organisation', 'The NHS code is not recorded.', !nhs || t.odsCode !== null);
  need('signin', 'Their Microsoft work accounts are not connected and confirmed yet.', verified);
  need('invite', 'Their administrator has not approved Overwatch yet.', consented);
  need('team', 'Their administrators’ team is not set up yet.', hasAdminTeam);
  need('roles', 'No team has been added to Overwatch yet besides the administrators.', hasOtherTeam);
  need('reach', 'The web address is not set.', detail.host !== null);
  need('reach', 'A text number has not been tested yet.', detail.numbers.some((n) => n.testedAt !== null));
  need('agreements', 'The data sharing agreement is not recorded.', refs.dsa !== null);
  need('agreements', 'The privacy impact assessment is not recorded.', refs.dpia !== null);
  need('agreements', 'The clinical safety case is not recorded.', refs.dcb0160 !== null);
  if (detail.activation !== null) {
    for (const blocker of detail.activation.blockers) {
      const item = describeBlocker(blocker);
      if (!missing.some((m) => m.step === item.step && m.words === item.words)) missing.push(item);
    }
  }

  const steps: FunnelStep[] = STEP_IDS.map((id, index) => {
    const mine = missing.filter((m) => m.step === id).map((m) => m.words);
    const done = id === 'golive' ? t.status !== 'provisioning' : mine.length === 0;
    return { id, number: index + 1, title: STEP_TITLES[id], done, missing: mine };
  });
  const next = steps.find((s) => !s.done)?.id ?? null;
  const beforeGoLive = steps.filter((s) => s.id !== 'golive');
  const canGoLive = t.status === 'provisioning' && detail.activation !== null && detail.activation.ready && beforeGoLive.every((s) => s.done) && missing.length === 0;
  return { steps, next, doneCount: steps.filter((s) => s.done).length, total: steps.length, canGoLive, missing };
}
