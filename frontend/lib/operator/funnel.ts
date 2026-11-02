import type { parseConsent, parseTenantDetail } from './views';
import { NHS_ORGANISATION_TYPE_CODES } from './words';

// The "Go live" funnel of a partner organisation's page: the steps in order, whether each is done, which one is next,
// and what the back end's activation blockers mean in plain words and for which step. The page shows the eight steps
// grouped into five parts (PHASES); the step logic is here, only the presentation groups. Derived only from the
// tenant detail and the consent invitation the page already reads; nothing here writes.

type Detail = ReturnType<typeof parseTenantDetail>;
export type Consent = ReturnType<typeof parseConsent>;
export type ConsentRead = { status: 'loading' } | { status: 'ok'; data: Consent } | { status: 'failed'; http: number };

export const STEP_IDS = ['organisation', 'signin', 'invite', 'team', 'roles', 'reach', 'agreements', 'golive'] as const;
export type StepId = (typeof STEP_IDS)[number];

export const STEP_TITLES: Record<StepId, string> = {
  organisation: 'Check the organisation',
  signin: 'Connect their Microsoft work accounts',
  invite: 'Ask their administrator to approve',
  team: 'Administrators’ team',
  roles: 'Other teams',
  reach: 'Web address and text number',
  agreements: 'Agreements',
  golive: 'Go live',
};

/** The five parts the operator sees. Each groups some of the steps above. */
export const PHASE_IDS = ['organisation', 'approval', 'teams', 'reach', 'golive'] as const;
export type PhaseId = (typeof PHASE_IDS)[number];
export const PHASES: readonly { id: PhaseId; title: string; steps: readonly StepId[] }[] = [
  { id: 'organisation', title: 'Organisation and sign-in', steps: ['organisation', 'signin'] },
  { id: 'approval', title: 'Administrator approval', steps: ['invite'] },
  { id: 'teams', title: 'Teams and people', steps: ['team', 'roles'] },
  { id: 'reach', title: 'Reach and agreements', steps: ['reach', 'agreements'] },
  { id: 'golive', title: 'Go live', steps: ['golive'] },
];

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

/** `by: 'them'` is something only the organisation's administrators can do once they sign in. */
type Missing = { step: StepId; key: string; by: 'operator' | 'them'; words: string };

const NEED = {
  nhs: 'The NHS code is not recorded.',
  signin: 'Their Microsoft work accounts are not connected and confirmed yet.',
  invite: 'Their administrator has not approved Overwatch yet.',
  team: 'Their administrators’ team is not set up yet.',
  roles: 'No other team has been added yet.',
  host: 'The web address is not set.',
  number: 'A text number has not been tested yet.',
  agreements: 'The agreements are not all recorded yet.',
} as const;

/** What each of the back end's activation blockers means, in words, the step it belongs to, and who can do it. */
function describeBlocker(blocker: string): Missing {
  const text = blocker.toLowerCase();
  const op = (step: StepId, key: string, words: string): Missing => ({ step, key, by: 'operator', words });
  const them = (key: string, words: string): Missing => ({ step: 'golive', key, by: 'them', words });
  if (text.includes('host')) return op('reach', 'host', NEED.host);
  if (text.includes('number') || text.includes('test text')) return op('reach', 'number', NEED.number);
  if (text.includes('time zone')) return op('organisation', 'time-zone', 'The time zone is not set.');
  if (text.includes('directory')) return op('signin', 'signin', NEED.signin);
  if (text.includes('email')) return op('invite', 'email', 'Overwatch cannot send email for this organisation yet. Tell the Overwatch team.');
  if (text.includes('administrator group')) return op('team', 'team', NEED.team);
  if (text.includes('role mapping')) return op('roles', 'roles', NEED.roles);
  if (text.includes('references')) return op('agreements', 'agreements', NEED.agreements);
  if (text.includes('network agreement')) return them('network', 'Accept the network agreement');
  if (text.includes('contacts')) return them('contacts', 'Set the support contacts');
  if (text.includes('retention')) return them('retention', 'Set how long records are kept');
  if (text.includes('districts')) return them('districts', 'Set the area’s districts');
  if (text.includes('names set') || text.includes('wording')) return them('names', 'Set the names they use for their systems');
  if (text.includes('configuration')) return them('config', 'Approve their settings');
  return op('golive', 'other', 'Something else still has to be finished. Tell the Overwatch team.');
}

export type FunnelStep = { id: StepId; number: number; title: string; done: boolean; missing: string[] };
export type PhaseState = 'completed' | 'in-progress' | 'not-started' | 'waiting';
export const PHASE_STATE_WORD: Record<PhaseState, string> = { completed: 'Completed', 'in-progress': 'In progress', 'not-started': 'Not started', waiting: 'Waiting for them' };

export type FunnelPhase = {
  id: PhaseId;
  number: number;
  title: string;
  steps: StepId[];
  done: boolean;
  state: PhaseState;
  /** One line on where this part stands. */
  summary: string;
  /** How many things the operator still has to do in it (no duplicates). */
  left: number;
};

export type Funnel = {
  steps: FunnelStep[];
  phases: FunnelPhase[];
  /** The step the operator should do next (the first that is not done). Null when every step is done. */
  next: StepId | null;
  /** The first part that is not completed: the one shown by default. Null when every part is completed. */
  nextPhase: PhaseId | null;
  doneCount: number;
  total: number;
  /** Every step before Go live is done and the back end agrees. Only then is the Go live button shown. */
  canGoLive: boolean;
  /** Everything still missing, with the step it belongs to and who can do it (no duplicates). */
  missing: Missing[];
  /** What is left for the operator, one entry per part that has anything left. */
  leftByPhase: { phase: PhaseId; title: string; count: number; waiting: boolean }[];
  /** What only the organisation's administrators can do once they sign in. */
  byThem: string[];
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function deriveFunnel(detail: Detail, consent: ConsentRead): Funnel {
  const t = detail.tenant;
  const bindings = detail.bindings.filter((b) => b.status !== 'revoked');
  const verified = detail.bindings.some((b) => b.status === 'verified');
  const invitation = consent.status === 'ok' ? consent.data.invitation : null;
  const consented = invitation?.status === 'consented';
  const mapped = detail.roleMappings.filter((m) => m.status === 'active');
  const hasAdminTeam = mapped.some((m) => m.role === 'tenant-admin');
  const otherTeams = mapped.filter((m) => m.role !== 'tenant-admin');
  const refs = t.references;
  const refCount = [refs.dsa, refs.dpia, refs.dcb0160].filter((r) => r !== null).length;

  const missing: Missing[] = [];
  const add = (item: Missing) => {
    if (!missing.some((m) => m.step === item.step && m.key === item.key)) missing.push(item);
  };
  const need = (step: StepId, key: keyof typeof NEED, ok: boolean) => {
    if (!ok) add({ step, key, by: 'operator', words: NEED[key] });
  };
  const nhs = NHS_ORGANISATION_TYPE_CODES.includes(t.organisationType);
  need('organisation', 'nhs', !nhs || t.odsCode !== null);
  need('signin', 'signin', verified);
  need('invite', 'invite', consented);
  need('team', 'team', hasAdminTeam);
  need('roles', 'roles', otherTeams.length > 0);
  need('reach', 'host', detail.host !== null);
  need('reach', 'number', detail.numbers.some((n) => n.testedAt !== null));
  need('agreements', 'agreements', refCount === 3);
  if (detail.activation !== null) for (const blocker of detail.activation.blockers) add(describeBlocker(blocker));

  const steps: FunnelStep[] = STEP_IDS.map((id, index) => {
    const mine = missing.filter((m) => m.step === id && m.by === 'operator').map((m) => m.words);
    const done = id === 'golive' ? t.status !== 'provisioning' : mine.length === 0;
    return { id, number: index + 1, title: STEP_TITLES[id], done, missing: mine };
  });
  const stepDone = (id: StepId) => steps.find((s) => s.id === id)!.done;
  const byThem = missing.filter((m) => m.by === 'them').map((m) => m.words);
  const leftIn = (ids: readonly StepId[]) => missing.filter((m) => m.by === 'operator' && ids.includes(m.step)).length;
  const beforeGoLive = steps.filter((s) => s.id !== 'golive');
  const allBeforeDone = beforeGoLive.every((s) => s.done) && leftIn(['golive']) === 0;

  const started: Record<PhaseId, boolean> = {
    organisation: stepDone('organisation') || bindings.length > 0,
    approval: invitation !== null,
    teams: hasAdminTeam || otherTeams.length > 0,
    reach: detail.host !== null || detail.numbers.length > 0 || refCount > 0,
    golive: false,
  };
  const summaries: Record<PhaseId, () => string> = {
    organisation: () => {
      if (stepDone('organisation') && stepDone('signin')) return 'NHS record checked. Microsoft work accounts connected.';
      if (!stepDone('organisation')) return missing.find((m) => m.step === 'organisation')!.words;
      return bindings.length === 0 ? 'No Microsoft work account is connected yet.' : 'A Microsoft work account is waiting for you to confirm it.';
    },
    approval: () => {
      if (consented) return 'Their administrator has approved Overwatch.';
      if (consent.status === 'failed') return 'We could not read the approval link.';
      if (invitation === null) return verified ? 'No approval link has been sent yet.' : 'Connect their Microsoft work accounts first.';
      if (invitation.status === 'expired') return 'The approval link has expired. Send a new one.';
      return 'Approval link sent. Waiting for their administrator.';
    },
    teams: () => {
      if (stepDone('team') && stepDone('roles')) return `Administrators’ team and ${plural(otherTeams.length, 'other team', 'other teams')} added.`;
      if (!consented) return 'Needs their administrator’s approval first.';
      if (!hasAdminTeam) return 'The administrators’ team is not added yet.';
      return 'Administrators’ team added. No other team yet.';
    },
    reach: () => {
      const tested = detail.numbers.some((n) => n.testedAt !== null);
      return `Web address ${detail.host !== null ? 'set' : 'not set'}. Text number ${tested ? 'tested' : 'not tested'}. Agreements ${refCount} of 3.`;
    },
    golive: () => {
      if (t.status !== 'provisioning') return t.status === 'active' ? 'Live.' : 'Not live.';
      const left = leftIn(STEP_IDS);
      if (left > 0) return `${plural(left, 'thing', 'things')} left.`;
      return byThem.length > 0 ? 'Their administrators finish the last steps.' : 'Ready to go live.';
    },
  };

  const phases: FunnelPhase[] = PHASES.map((p, index) => {
    const done = p.steps.every(stepDone);
    let state: PhaseState = started[p.id] ? 'in-progress' : 'not-started';
    if (p.id === 'approval' && invitation?.status === 'pending') state = 'waiting';
    if (p.id === 'golive' && allBeforeDone) state = byThem.length > 0 ? 'waiting' : 'in-progress';
    if (done) state = 'completed';
    return { id: p.id, number: index + 1, title: p.title, steps: [...p.steps], done, state, summary: summaries[p.id](), left: leftIn(p.steps) };
  });

  const canGoLive = t.status === 'provisioning' && detail.activation !== null && detail.activation.ready && allBeforeDone && missing.length === 0;
  return {
    steps,
    phases,
    next: steps.find((s) => !s.done)?.id ?? null,
    nextPhase: phases.find((p) => !p.done)?.id ?? null,
    doneCount: steps.filter((s) => s.done).length,
    total: steps.length,
    canGoLive,
    missing,
    leftByPhase: phases.filter((p) => p.left > 0).map((p) => ({ phase: p.id, title: p.title, count: p.left, waiting: p.state === 'waiting' })),
    byThem,
  };
}
