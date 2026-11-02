'use client';

import { useState, type FormEvent, type ReactNode } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { operatorSend } from '@/lib/operator/browser';
import { STEP_IDS, TEAM_WORDS, teamName, type ConsentRead, type FunnelStep } from '@/lib/operator/funnel';
import type { parseTenantDetail } from '@/lib/operator/views';
import { organisationTypeWord } from '@/lib/operator/words';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// The steps of an organisation's "Go live" page (TEN-083): each step is one card with one next action, plain words,
// and a collapsed "Details" section that holds the technical identifiers. The writes are the same as ever (same
// routes, same bodies); only the layout and the words changed. A step that was done and not recorded by the platform
// chain (`recorded: false`) is passed up so the page says so.

export type Detail = ReturnType<typeof parseTenantDetail>;
type Say = { ok: boolean; text: string } | null;

export type PanelProps = {
  tenantId: string;
  detail: Detail;
  consent: ConsentRead;
  step: FunnelStep;
  isNext: boolean;
  onChanged: () => void;
  onUnrecorded: () => void;
};

function Said({ say }: { say: Say }) {
  if (say === null) return null;
  return (
    <p role={say.ok ? 'status' : 'alert'} className={say.ok ? styles.ok : styles.problem}>
      {say.text}
    </p>
  );
}

const STATE_WORD = { done: 'Done', next: 'Next', todo: 'To do' } as const;

/** One step as a card: its place in the list, whether it is done or next, then its content and its Details. */
export function StepCard({ step, isNext, children, details }: { step: FunnelStep; isNext: boolean; children: ReactNode; details?: ReactNode }) {
  const state = step.done ? 'done' : isNext ? 'next' : 'todo';
  return (
    <div id={`step-${step.id}`} data-el={`OP-STEP-${step.id.toUpperCase()}`} data-state={state}>
      <Card heading={step.title}>
        <p className={styles.row}>
          <span className={styles.muted}>{`Step ${step.number} of ${STEP_IDS.length}`}</span>
          <span className={state === 'done' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{STATE_WORD[state]}</span>
        </p>
        {children}
        {details !== undefined ? (
          <details className={styles.details}>
            <summary>Details</summary>
            <div className={styles.stack}>{details}</div>
          </details>
        ) : null}
      </Card>
    </div>
  );
}

const E164 = /^\+[1-9]\d{6,14}$/;
const WORK_EMAIL = /^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;
const NUMBER_STATE: Record<string, string> = { active: 'In use', retired: 'Stopped', quarantined: 'On hold' };

type MadeGroup = { role: string; name: string; groupId: string; created: boolean; assigned: boolean };
type RunData = { recorded?: boolean; expiresAt?: string; groups?: MadeGroup[]; added?: boolean };

/** One write of a panel: the key of this submit, busy, and what to say. */
function useWrite(tenantId: string, props: Pick<PanelProps, 'onChanged' | 'onUnrecorded'>) {
  const submitKey = useSubmitKey();
  const [busy, setBusy] = useState(false);
  const [say, setSay] = useState<Say>(null);
  async function run(method: 'POST' | 'PUT', sub: string, body: unknown, done: (data: RunData) => string, failed: (status: number) => string): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setSay(null);
    const result = await operatorSend<RunData>(method, `/api/bff/platform/tenants/${tenantId}/${sub}`, body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setSay({ ok: true, text: done(result.data) });
      if (result.data.recorded === false) props.onUnrecorded();
      props.onChanged();
      return true;
    }
    setSay({ ok: false, text: failed(result.status) });
    return false;
  }
  return { run, busy, say, setSay, fresh: submitKey.fresh };
}

const COUNTRY_WORD: Record<string, string> = { GB: 'United Kingdom', IE: 'Ireland' };

/** Step 1. The organisation as the NHS record gave it. Nothing here is written: the record is read-only once created. */
export function OrganisationStep(props: PanelProps) {
  const t = props.detail.tenant;
  return (
    <StepCard
      step={props.step}
      isNext={props.isNext}
      details={
        <dl className={styles.facts}>
          <dt>Organisation id</dt>
          <dd>{t.id}</dd>
          <dt>ODS code</dt>
          <dd>{t.odsCode ?? '-'}</dd>
          <dt>Created</dt>
          <dd>{whenText(t.createdAt)}</dd>
        </dl>
      }
    >
      <p className={styles.text}>Check these are right. They were taken from the NHS record when the organisation was created, and cannot be changed here.</p>
      <dl className={styles.facts}>
        <dt>Name</dt>
        <dd>{t.displayName}</dd>
        <dt>Legal name</dt>
        <dd>{t.legalName}</dd>
        <dt>Type</dt>
        <dd>{organisationTypeWord(t.organisationType)}</dd>
        <dt>NHS code</dt>
        <dd>{t.odsCode ?? 'None'}</dd>
        <dt>Country</dt>
        <dd>{COUNTRY_WORD[t.countryCode] ?? t.countryCode}</dd>
        <dt>Time zone</dt>
        <dd>{t.timeZone}</dd>
      </dl>
    </StepCard>
  );
}

const BINDING_WORD = { pending: 'Waiting for you to confirm', verified: 'Confirmed', revoked: 'Replaced' } as const;

type Lookup = { domain: string; directoryId: string | null } | 'not-valid' | null;

/**
 * Step 2. Their sign-in: the Microsoft work accounts the organisation's staff use. The organisation (or the operator when
 * creating it) names the account; the operator checks that it is theirs and confirms it with one button. The lookup
 * from the organisation's domain is a read: it saves nothing.
 */
export function SignInStep(props: PanelProps) {
  const write = useWrite(props.tenantId, props);
  const [domain, setDomain] = useState('');
  const [lookup, setLookup] = useState<Lookup>(null);
  const bindings = props.detail.bindings.filter((b) => b.status !== 'revoked');
  const waiting = bindings.find((b) => b.status === 'pending');
  const confirmed = bindings.find((b) => b.status === 'verified');
  const name = props.detail.tenant.displayName;

  async function look(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLookup(null);
    const response = await fetch(`/api/bff/platform/directory-lookup?domain=${encodeURIComponent(domain.trim())}`, { cache: 'no-store' });
    if (!response.ok) {
      setLookup('not-valid');
      return;
    }
    setLookup((await response.json()) as { domain: string; directoryId: string | null });
  }
  const bound = confirmed ?? waiting;

  return (
    <StepCard
      step={props.step}
      isNext={props.isNext}
      details={
        bindings.length === 0 ? (
          <p className={styles.muted}>Nothing is connected, so there is nothing to show yet.</p>
        ) : (
          <div className={styles.scroll}>
            <table className={`${styles.table} ${styles.stackTable}`}>
              <caption>Connected Microsoft accounts</caption>
              <thead>
                <tr>
                  <th scope="col">Directory id</th>
                  <th scope="col">State</th>
                  <th scope="col">Confirmed</th>
                </tr>
              </thead>
              <tbody>
                {bindings.map((b) => (
                  <tr key={b.directoryId}>
                    <td data-label="Directory id">{b.directoryId}</td>
                    <td data-label="State">{BINDING_WORD[b.status]}</td>
                    <td data-label="Confirmed">{whenText(b.verifiedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    >
      <p className={styles.text}>People at the organisation sign in to Overwatch with their Microsoft work accounts. Overwatch needs to know which Microsoft account is theirs.</p>
      {confirmed !== undefined ? (
        <p className={styles.ok}>{`Connected to ${name}’s Microsoft accounts.`}</p>
      ) : waiting !== undefined ? (
        <>
          <p className={styles.text}>{`A Microsoft account has been named for ${name}. Check that it is theirs, then confirm it. Nobody can sign in with it until you do.`}</p>
          <Said say={write.say} />
          <div className={styles.actions}>
            <Button variant="primary" busy={write.busy} onClick={() => void write.run('POST', 'directory/verification', { directoryId: waiting.directoryId }, () => 'Confirmed. Their people can now sign in with their Microsoft work accounts.', () => 'It could not be confirmed. Try again.')}>
              Confirm this is their Microsoft account
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className={styles.text}>No Microsoft account is connected yet.</p>
          <p className={styles.muted}>Their administrator can connect it from the Users and roles page in their own Overwatch. Use the check below to find it from their email domain.</p>
        </>
      )}
      <form className={styles.stack} onSubmit={(event) => void look(event)} noValidate aria-label="Find their Microsoft account">
        <TextField id="signin-domain" label="Their email domain" value={domain} onChange={setDomain} requirement="optional" hint="For example example.nhs.uk. This only looks; it saves nothing." autoComplete="off" dataEl="OP-TENANT-DOMAIN-INPUT" />
        <div className={styles.actions}>
          <Button variant="neutral" type="submit" dataEl="OP-TENANT-DOMAIN-LOOKUP-BTN">
            Look up their Microsoft account
          </Button>
        </div>
      </form>
      {lookup === 'not-valid' ? (
        <p role="status" className={styles.text}>
          Enter a domain name, for example example.nhs.uk.
        </p>
      ) : lookup !== null ? (
        <div className={styles.panel} data-el="OP-TENANT-DOMAIN-CARD" role="status">
          {lookup.directoryId === null ? (
            <p className={styles.text}>{`No Microsoft account was found for ${lookup.domain}. Ask the organisation which one they use.`}</p>
          ) : (
            <>
              <p className={styles.text}>{`Found a Microsoft account for ${lookup.domain}.`}</p>
              <p className={styles.text}>
                {bound === undefined
                  ? 'None is connected here yet.'
                  : bound.directoryId.toLowerCase() === lookup.directoryId.toLowerCase()
                    ? 'It is the same one that is connected here.'
                    : 'It is not the one that is connected here. Check before you confirm.'}
              </p>
            </>
          )}
        </div>
      ) : null}
    </StepCard>
  );
}

const CONSENT_WORD: Record<string, string> = {
  pending: 'Waiting for approval',
  consented: 'Approved',
  expired: 'The link has expired',
  revoked: 'Replaced by a newer link',
};

/**
 * Step 3. Their administrator is emailed a link to approve Overwatch in their own Microsoft account (DEC-1316). The page
 * shows only the masked address and where the link stands; the address is never shown or kept in the clear. "Approved" is
 * only ever what the back end confirmed.
 */
export function InviteStep(props: PanelProps) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const write = useWrite(props.tenantId, props);
  const hasSignIn = props.detail.bindings.some((b) => b.status !== 'revoked');
  const consent = props.consent;
  const invitation = consent.status === 'ok' ? consent.data.invitation : null;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const address = email.trim();
    if (!WORK_EMAIL.test(address) || address.includes('..')) {
      setError('Enter the administrator’s work email address, for example name@organisation.nhs.uk.');
      return;
    }
    setError(null);
    void write
      .run(
        'POST',
        'admin-consent-invitation',
        { email: address },
        () => 'The approval link was emailed. It works for 7 days. The address is not shown again.',
        (status) => (status === 403 || status === 404 || status === 409 ? 'The link could not be sent. Connect their sign-in first (step 2), and check that Overwatch can send email.' : 'The link could not be sent. Try again.'),
      )
      .then((ok) => {
        if (ok) setEmail('');
      });
  }
  return (
    <StepCard
      step={props.step}
      isNext={props.isNext}
      details={
        invitation === null ? (
          <p className={styles.muted}>No link has been sent.</p>
        ) : (
          <dl className={styles.facts} aria-label="Latest approval link">
            <dt>Sent to</dt>
            <dd>{invitation.emailMasked}</dd>
            <dt>Sent</dt>
            <dd>{whenText(invitation.createdAt)}</dd>
            <dt>{invitation.status === 'consented' ? 'Approved' : 'Valid until'}</dt>
            <dd>{whenText(invitation.status === 'consented' ? invitation.consentedAt : invitation.expiresAt)}</dd>
            {invitation.status === 'pending' && invitation.reason !== null ? (
              <>
                <dt>Last check</dt>
                <dd>{invitation.reason}</dd>
              </>
            ) : null}
          </dl>
        )
      }
    >
      <p className={styles.text}>
        Their administrator opens the link and approves Overwatch in their own Microsoft account. Approving lets Overwatch make teams there, add people to them and find people by email address. It does not let Overwatch read anyone’s email or files.
      </p>
      {consent.status === 'loading' ? <p className={styles.muted}>Loading.</p> : null}
      {consent.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the state of the approval link.
        </p>
      ) : null}
      {consent.status === 'ok' ? (
        invitation === null ? (
          <p className={styles.text}>No approval link has been sent yet.</p>
        ) : invitation.status === 'consented' ? (
          <p className={styles.ok}>{`Approved on ${whenText(invitation.consentedAt)}. Their administrator has approved Overwatch.`}</p>
        ) : invitation.status === 'expired' ? (
          <p className={styles.problem}>The approval link has expired. Send a new one.</p>
        ) : (
          <p className={styles.text}>{`${CONSENT_WORD[invitation.status] ?? 'Waiting for approval'}. The link went to ${invitation.emailMasked} and works until ${whenText(invitation.expiresAt)}.`}</p>
        )
      ) : null}
      {invitation?.status === 'consented' ? null : hasSignIn ? (
        <form className={styles.stack} onSubmit={submit} noValidate aria-label="Send the approval link">
          <TextField id="consent-email" label="Their administrator’s work email" value={email} onChange={(v) => { write.fresh(); setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={error} />
          <Said say={write.say} />
          <div className={styles.actions}>
            <Button variant="secondary" type="submit" busy={write.busy}>
              {invitation === null ? 'Send the approval link to their administrator' : 'Send the link again'}
            </Button>
          </div>
        </form>
      ) : (
        <p className={styles.text}>Connect their sign-in first (step 2). The approval link is for their Microsoft account.</p>
      )}
    </StepCard>
  );
}

function isConsented(consent: ConsentRead): boolean {
  return consent.status === 'ok' && consent.data.invitation?.status === 'consented';
}

const GROUP_FAILED = (status: number): string =>
  status === 404
    ? 'The teams could not be made. Check that their administrator has approved Overwatch.'
    : status === 503
      ? 'Their Microsoft account could not be reached. Try again in a minute.'
      : status === 409
        ? 'A team already gives a different role. Nothing was changed.'
        : 'The teams could not be made. Try again.';

function useMemberForm(props: PanelProps, role: () => string, noun: string) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const member = useWrite(props.tenantId, props);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const address = email.trim();
    if (!WORK_EMAIL.test(address) || address.includes('..')) {
      setError('Enter the person’s work email address, for example name@organisation.nhs.uk.');
      return;
    }
    setError(null);
    void member
      .run('POST', 'entra-groups/members', { role: role(), email: address }, (data) => (data.added === false ? `That person is already in the ${noun}.` : `Added to the ${noun}. The address is not kept.`), (status) =>
        status === 400
          ? 'No one in their Microsoft accounts has that email address.'
          : status === 404
            ? `That ${noun} has not been made yet.`
            : status === 503
              ? 'Their Microsoft account could not be reached. Try again in a minute.'
              : 'The person could not be added. Try again.',
      )
      .then((ok) => {
        if (ok) setEmail('');
      });
  }
  return { email, setEmail, error, member, submit };
}

/**
 * Step 4 (DEC-1317): once their administrator has approved, make their administrators’ team, then put the first people in
 * it. The team's name is made by the back end from the organisation's code, never typed. The administrators’ team is the
 * only route to administrator rights. Who is in a team is held in their Microsoft account, not by Overwatch.
 */
export function TeamStep(props: PanelProps) {
  const consented = isConsented(props.consent);
  const [made, setMade] = useState<MadeGroup[]>([]);
  const groups = useWrite(props.tenantId, props);
  const mapped = props.detail.roleMappings.filter((m) => m.status === 'active');
  const hasTeam = mapped.some((m) => m.role === 'tenant-admin') || made.some((g) => g.role === 'tenant-admin');
  const form = useMemberForm(props, () => 'tenant-admin', 'team');
  function makeTeam() {
    void groups.run(
      'POST',
      'entra-groups',
      { roles: [] },
      (data) => {
        setMade(data.groups ?? []);
        return 'Their administrators’ team is in place.';
      },
      GROUP_FAILED,
    );
  }
  return (
    <StepCard
      step={props.step}
      isNext={props.isNext}
      details={
        <>
          {made.length > 0 ? (
            <div className={styles.scroll}>
              <table className={styles.table}>
                <caption>Teams just made</caption>
                <thead>
                  <tr>
                    <th scope="col">Team</th>
                    <th scope="col">Group name</th>
                    <th scope="col">State</th>
                  </tr>
                </thead>
                <tbody>
                  {made.map((g) => (
                    <tr key={g.groupId}>
                      <td>{teamName(g.role)}</td>
                      <td>{g.name}</td>
                      <td>{g.created ? 'Made now' : 'Already there'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption>Administrators’ team in Microsoft</caption>
              <thead>
                <tr>
                  <th scope="col">Team</th>
                  <th scope="col">Group object id</th>
                </tr>
              </thead>
              <tbody>
                {mapped.filter((m) => m.role === 'tenant-admin').length === 0 ? (
                  <tr>
                    <td colSpan={2}>Not made yet.</td>
                  </tr>
                ) : (
                  mapped
                    .filter((m) => m.role === 'tenant-admin')
                    .map((m) => (
                      <tr key={m.groupObjectId}>
                        <td>{teamName(m.role)}</td>
                        <td>{m.groupObjectId}</td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
        </>
      }
    >
      <p className={styles.text}>The administrators’ team is the only way anyone gets administrator rights in Overwatch. They run the organisation’s own pages: who is in which team, and its settings.</p>
      {props.consent.status === 'loading' ? <p className={styles.muted}>Loading.</p> : null}
      {props.consent.status === 'ok' && !consented ? <p className={styles.text}>You can create their administrators’ team once their administrator has approved Overwatch (step 3).</p> : null}
      {consented && !hasTeam ? (
        <>
          <Said say={groups.say} />
          <div className={styles.actions}>
            <Button variant="primary" busy={groups.busy} onClick={makeTeam}>
              Create their administrators’ team
            </Button>
          </div>
        </>
      ) : null}
      {consented && hasTeam ? (
        <>
          <p className={styles.ok}>Their administrators’ team is added to Overwatch.</p>
          <Said say={groups.say} />
          <form className={styles.stack} onSubmit={form.submit} noValidate aria-label="Add the first administrator by email">
            <TextField id="first-admin-email" label="Administrator’s work email" value={form.email} onChange={(v) => { form.member.fresh(); form.setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={form.error} />
            <Said say={form.member.say} />
            <div className={styles.actions}>
              <Button variant="secondary" type="submit" busy={form.member.busy}>
                Add the first administrator by email
              </Button>
            </div>
          </form>
        </>
      ) : null}
    </StepCard>
  );
}

/** Step 5. The other teams and what each can do. A team is added to Overwatch once, by ticking it here. */
export function RolesStep(props: PanelProps) {
  const consented = isConsented(props.consent);
  const [ticked, setTicked] = useState<string[]>([]);
  const [made, setMade] = useState<MadeGroup[]>([]);
  const groups = useWrite(props.tenantId, props);
  const mapped = props.detail.roleMappings.filter((m) => m.status === 'active');
  const has = (code: string) => mapped.some((m) => m.role === code) || made.some((g) => g.role === code);
  const memberChoices = TEAM_WORDS.filter(([code]) => has(code));
  const [memberRole, setMemberRole] = useState('');
  const chosenRole = memberChoices.some(([code]) => code === memberRole) ? memberRole : (memberChoices[0]?.[0] ?? '');
  const form = useMemberForm(props, () => chosenRole, 'team');
  function toggle(code: string, on: boolean) {
    groups.fresh();
    setTicked((held) => (on ? [...held, code] : held.filter((c) => c !== code)));
  }
  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void groups
      .run(
        'POST',
        'entra-groups',
        { roles: ticked },
        (data) => {
          setMade(data.groups ?? []);
          return 'The teams are added to Overwatch.';
        },
        GROUP_FAILED,
      )
      .then((ok) => {
        if (ok) setTicked([]);
      });
  }
  const rest = mapped.filter((m) => m.role !== 'tenant-admin');
  return (
    <StepCard
      step={props.step}
      isNext={props.isNext}
      details={
        <div className={styles.scroll}>
          <table className={`${styles.table} ${styles.stackTable}`}>
            <caption>Teams in Microsoft</caption>
            <thead>
              <tr>
                <th scope="col">Team</th>
                <th scope="col">Group object id</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {rest.length === 0 ? (
                <tr>
                  <td colSpan={3}>No team is added yet.</td>
                </tr>
              ) : (
                rest.map((m) => (
                  <tr key={`${m.groupObjectId}-${m.role}`}>
                    <td data-label="Team">{teamName(m.role)}</td>
                    <td data-label="Group object id">{m.groupObjectId}</td>
                    <td data-label="State">{m.status === 'active' ? 'In use' : 'Stopped'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      }
    >
      <p className={styles.text}>Everyone else works in one of these teams. Being in a team is what lets a person do its work in Overwatch. The administrators’ team above is the only route to administrator rights: none of these teams gives them.</p>
      {props.consent.status === 'ok' && !consented ? <p className={styles.text}>Teams can be added once their administrator has approved Overwatch (step 3).</p> : null}
      <form className={styles.stack} onSubmit={add} noValidate aria-label="Add teams to Overwatch">
        <ul className={styles.list}>
          {TEAM_WORDS.map(([code, word, can]) => (
            <li key={code}>
              {has(code) ? (
                <strong>{word}</strong>
              ) : consented ? (
                <label>
                  <input type="checkbox" checked={ticked.includes(code)} onChange={(event) => toggle(code, event.target.checked)} /> <strong>{word}</strong>
                </label>
              ) : (
                <strong>{word}</strong>
              )}{' '}
              <span className={has(code) ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{has(code) ? 'Added to Overwatch' : 'Not added yet'}</span>
              <br />
              <span className={styles.muted}>{can}</span>
            </li>
          ))}
        </ul>
        <Said say={groups.say} />
        {consented ? (
          <div className={styles.actions}>
            <Button variant="secondary" type="submit" busy={groups.busy} disabled={ticked.length === 0}>
              Add the ticked teams
            </Button>
          </div>
        ) : null}
      </form>
      {consented && memberChoices.length > 0 ? (
        <form className={styles.stack} onSubmit={form.submit} noValidate aria-label="Add a person to a team">
          <div className={styles.selectLabel}>
            <label htmlFor="team-member-team">Team</label>
            <select id="team-member-team" className={styles.select} value={chosenRole} onChange={(event) => { form.member.fresh(); setMemberRole(event.target.value); }}>
              {memberChoices.map(([code, word]) => (
                <option key={code} value={code}>
                  {word}
                </option>
              ))}
            </select>
          </div>
          <TextField id="team-member-email" label="Person’s work email" value={form.email} onChange={(v) => { form.member.fresh(); form.setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={form.error} />
          <Said say={form.member.say} />
          <div className={styles.actions}>
            <Button variant="secondary" type="submit" busy={form.member.busy}>
              Add to team
            </Button>
          </div>
        </form>
      ) : null}
    </StepCard>
  );
}

/** Step 6. The web address people use, and the text number their messages come from, with the sender name. */
export function ReachStep(props: PanelProps) {
  const [host, setHost] = useState('');
  const hostWrite = useWrite(props.tenantId, props);
  const [number, setNumber] = useState('');
  const [account, setAccount] = useState('');
  const [sender, setSender] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const write = useWrite(props.tenantId, props);
  const tested = useWrite(props.tenantId, props);

  function saveHost(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void hostWrite.run('PUT', 'host', { host: host.trim() }, () => 'Web address saved.', (status) => (status === 409 ? 'That web address is used by another organisation.' : 'The web address could not be saved. Try again.'));
  }
  function record(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!E164.test(number.trim())) next.number = 'Enter the number in international form, for example +441632960003.';
    if (account.trim() === '') next.account = 'Enter the text account.';
    if (sender.trim() === '') next.sender = 'Enter the sender name.';
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    void write
      .run('POST', 'numbers', { e164: number.trim(), accountSid: account.trim(), senderLabel: sender.trim() }, () => 'Text number recorded.', (status) => (status === 409 ? 'That number is used by another organisation.' : 'The text number could not be recorded. Try again.'))
      .then((ok) => {
        if (ok) {
          setNumber('');
          setAccount('');
          setSender('');
        }
      });
  }
  const numbers = props.detail.numbers;
  return (
    <StepCard
      step={props.step}
      isNext={props.isNext}
      details={
        numbers.length === 0 ? (
          <p className={styles.muted}>No text number is recorded.</p>
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption>Text number accounts</caption>
              <thead>
                <tr>
                  <th scope="col">Number</th>
                  <th scope="col">Account</th>
                  <th scope="col">Sending key</th>
                </tr>
              </thead>
              <tbody>
                {numbers.map((n) => (
                  <tr key={n.e164}>
                    <th scope="row">{n.e164}</th>
                    <td>{n.accountSid}</td>
                    <td>{n.hasSecret ? 'Held' : 'Not set'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    >
      <h3 className={styles.subheading}>Web address</h3>
      <p className={styles.text}>{props.detail.host === null ? 'No web address is set yet.' : `Their web address is ${props.detail.host}.`}</p>
      <form className={styles.stack} onSubmit={saveHost} noValidate aria-label="Set the web address">
        <TextField id="tenant-host" label="Web address" value={host} onChange={(v) => { hostWrite.fresh(); setHost(v); }} requirement="none" hint="What people type to reach Overwatch for this organisation." />
        <Said say={hostWrite.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={hostWrite.busy}>
            Save web address
          </Button>
        </div>
      </form>

      <h3 className={styles.subheading}>Text number</h3>
      <p className={styles.text}>Their text messages are sent from their own number, set up here. Send a test text to it, then mark the test as done.</p>
      {numbers.length === 0 ? (
        <p className={styles.text}>No text number is recorded yet.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption>Text numbers</caption>
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col">State</th>
                <th scope="col">Test</th>
                <th scope="col">
                  <span className={styles.srOnly}>Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {numbers.map((n) => (
                <tr key={n.e164}>
                  <th scope="row">{n.e164}</th>
                  <td>{NUMBER_STATE[n.status] ?? n.status}</td>
                  <td>{n.testedAt === null ? 'Not tested' : `Tested ${whenText(n.testedAt)}`}</td>
                  <td>
                    {n.testedAt === null ? (
                      <Button variant="neutral" busy={tested.busy} ariaLabel={`Mark ${n.e164} as tested`} onClick={() => void tested.run('POST', 'numbers/tested', { e164: n.e164 }, () => 'Text number marked as tested.', () => 'The text number could not be marked. Try again.')}>
                        Mark as tested
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Said say={tested.say} />
      <form className={styles.stack} onSubmit={record} noValidate aria-label="Record a text number">
        <TextField id="number-e164" label="Text number" value={number} onChange={(v) => { write.fresh(); setNumber(v); }} requirement="none" hint="In international form, with the plus sign." error={errors.number} />
        <TextField id="number-account" label="Text account" value={account} onChange={(v) => { write.fresh(); setAccount(v); }} requirement="none" hint="The account the number belongs to at the text message provider." error={errors.account} />
        <TextField id="number-sender" label="Sender name" value={sender} onChange={(v) => { write.fresh(); setSender(v); }} requirement="none" hint="The name people see the texts come from." error={errors.sender} />
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={write.busy}>
            Record text number
          </Button>
        </div>
      </form>
    </StepCard>
  );
}

/** Step 7. The three agreements, each named by a reference. Any one can be sent alone; each is optional text. */
export function AgreementsStep(props: PanelProps) {
  const [dsa, setDsa] = useState('');
  const [dpia, setDpia] = useState('');
  const [dcb, setDcb] = useState('');
  const [problem, setProblem] = useState('');
  const write = useWrite(props.tenantId, props);
  const refs = props.detail.tenant.references;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Record<string, string> = {};
    if (dsa.trim() !== '') body.dsaRef = dsa.trim();
    if (dpia.trim() !== '') body.dpiaRef = dpia.trim();
    if (dcb.trim() !== '') body.dcb0160Ref = dcb.trim();
    if (Object.keys(body).length === 0) {
      setProblem('Enter at least one reference.');
      return;
    }
    setProblem('');
    void write.run('PUT', 'references', body, () => 'Agreements saved.', () => 'The agreements could not be saved. Try again.').then((ok) => {
      if (ok) {
        setDsa('');
        setDpia('');
        setDcb('');
      }
    });
  }
  const held = (v: string | null) => v ?? 'Not recorded';
  return (
    <StepCard step={props.step} isNext={props.isNext}>
      <p className={styles.text}>Record the reference of each agreement that is in place. Overwatch keeps the reference, not the document. Each can be a number, a code or a few words.</p>
      <dl className={styles.facts}>
        <dt>Data sharing agreement</dt>
        <dd>{held(refs.dsa)}</dd>
        <dt>Privacy impact assessment</dt>
        <dd>{held(refs.dpia)}</dd>
        <dt>Clinical safety case</dt>
        <dd>{held(refs.dcb0160)}</dd>
      </dl>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Record the agreements">
        <TextField id="ref-dsa" label="Data sharing agreement" value={dsa} onChange={(v) => { write.fresh(); setDsa(v); }} requirement="optional" />
        <TextField id="ref-dpia" label="Privacy impact assessment" value={dpia} onChange={(v) => { write.fresh(); setDpia(v); }} requirement="optional" />
        <TextField id="ref-dcb" label="Clinical safety case" value={dcb} onChange={(v) => { write.fresh(); setDcb(v); }} requirement="optional" />
        {problem !== '' ? <p className={styles.problem}>{problem}</p> : null}
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={write.busy}>
            Save agreements
          </Button>
        </div>
      </form>
    </StepCard>
  );
}
