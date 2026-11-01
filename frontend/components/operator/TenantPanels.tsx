'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { operatorSend, useOperatorRead } from '@/lib/operator/browser';
import type { parseConsent, parseTenantDetail } from '@/lib/operator/views';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { MAPPABLE_ROLE_WORDS } from '@/lib/tenantAdmin/roles';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// The provisioning panels of a tenant's page (TEN-083): the address, the text numbers, the agreement
// references, the directory and the first administrator. Each is one small form with its own words. A step
// that was done and not recorded by the platform chain (`recorded: false`) is passed up so the page says so.

export type Detail = ReturnType<typeof parseTenantDetail>;
type Say = { ok: boolean; text: string } | null;

type PanelProps = { tenantId: string; detail: Detail; onChanged: () => void; onUnrecorded: () => void };

function Said({ say }: { say: Say }) {
  if (say === null) return null;
  return (
    <p role={say.ok ? 'status' : 'alert'} className={say.ok ? styles.ok : styles.problem}>
      {say.text}
    </p>
  );
}

function roleName(code: string): string {
  return MAPPABLE_ROLE_WORDS.find(([value]) => value === code)?.[1] ?? code;
}

const NUMBER_STATE: Record<string, string> = { active: 'In use', retired: 'Stopped', quarantined: 'Quarantined' };
const E164 = /^\+[1-9]\d{6,14}$/;

/** One write of a panel: the key of this submit, busy, and what to say. */
function useWrite(tenantId: string, props: Pick<PanelProps, 'onChanged' | 'onUnrecorded'>) {
  const submitKey = useSubmitKey();
  const [busy, setBusy] = useState(false);
  const [say, setSay] = useState<Say>(null);
  async function run(method: 'POST' | 'PUT', sub: string, body: unknown, done: (data: { recorded?: boolean; expiresAt?: string }) => string, failed: (status: number) => string): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setSay(null);
    const result = await operatorSend<{ recorded?: boolean; expiresAt?: string }>(method, `/api/bff/platform/tenants/${tenantId}/${sub}`, body, submitKey.key());
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

export function HostPanel(props: PanelProps) {
  const [host, setHost] = useState('');
  const write = useWrite(props.tenantId, props);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void write.run('PUT', 'host', { host: host.trim() }, () => 'Address saved.', (status) => (status === 409 ? 'That address is held by another tenant.' : 'The address could not be saved. Try again.'));
  }
  return (
    <Card heading="Where the tenant is reached">
      <p className={styles.text}>{props.detail.host === null ? 'No address is set yet.' : `Now ${props.detail.host}.`}</p>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Set the address">
        <TextField id="tenant-host" label="Address" value={host} onChange={(v) => { write.fresh(); setHost(v); }} requirement="none" hint="The host name people use to reach this tenant." />
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={write.busy}>
            Save address
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function NumbersPanel(props: PanelProps) {
  const [number, setNumber] = useState('');
  const [account, setAccount] = useState('');
  const [sender, setSender] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const write = useWrite(props.tenantId, props);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!E164.test(number.trim())) next.number = 'Enter the number in international form, for example +441632960003.';
    if (account.trim() === '') next.account = 'Enter the account.';
    if (sender.trim() === '') next.sender = 'Enter the sender name.';
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    void write
      .run('POST', 'numbers', { e164: number.trim(), accountSid: account.trim(), senderLabel: sender.trim() }, () => 'Number recorded.', (status) => (status === 409 ? 'That number is held by another tenant.' : 'The number could not be recorded. Try again.'))
      .then((ok) => {
        if (ok) {
          setNumber('');
          setAccount('');
          setSender('');
        }
      });
  }
  const tested = useWrite(props.tenantId, props);
  return (
    <Card heading="Text numbers">
      <p className={styles.text}>The tenant’s text messages are sent from these numbers. They are the organisation’s own lines, set up here and not by the tenant.</p>
      {props.detail.numbers.length === 0 ? (
        <p className={styles.text}>No number is recorded yet.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption>Text numbers</caption>
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col">Account</th>
                <th scope="col">State</th>
                <th scope="col">Tested</th>
                <th scope="col">Auth token</th>
                <th scope="col">
                  <span className={styles.srOnly}>Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {props.detail.numbers.map((n) => (
                <tr key={n.e164}>
                  <th scope="row">{n.e164}</th>
                  <td>{n.accountSid}</td>
                  <td>{NUMBER_STATE[n.status] ?? n.status}</td>
                  <td>{n.testedAt === null ? 'Not tested' : whenText(n.testedAt)}</td>
                  <td>{n.hasSecret ? 'Auth token held' : 'Auth token not set'}</td>
                  <td>
                    {n.testedAt === null ? (
                      <Button variant="neutral" busy={tested.busy} ariaLabel={`Mark ${n.e164} as tested`} onClick={() => void tested.run('POST', 'numbers/tested', { e164: n.e164 }, () => 'Number marked as tested.', () => 'The number could not be marked. Try again.')}>
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
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Record a number">
        <TextField id="number-e164" label="Number" value={number} onChange={(v) => { write.fresh(); setNumber(v); }} requirement="none" hint="In international form, with the plus sign." error={errors.number} />
        <TextField id="number-account" label="Account" value={account} onChange={(v) => { write.fresh(); setAccount(v); }} requirement="none" error={errors.account} />
        <TextField id="number-sender" label="Sender name" value={sender} onChange={(v) => { write.fresh(); setSender(v); }} requirement="none" error={errors.sender} />
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={write.busy}>
            Record number
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function ReferencesPanel(props: PanelProps) {
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
    void write.run('PUT', 'references', body, () => 'References saved.', () => 'The references could not be saved. Try again.').then((ok) => {
      if (ok) {
        setDsa('');
        setDpia('');
        setDcb('');
      }
    });
  }
  const held = (v: string | null) => v ?? 'Not recorded';
  return (
    <Card heading="Agreements">
      <dl className={styles.facts}>
        <dt>Data sharing agreement</dt>
        <dd>{held(refs.dsa)}</dd>
        <dt>Privacy impact assessment</dt>
        <dd>{held(refs.dpia)}</dd>
        <dt>Clinical safety case</dt>
        <dd>{held(refs.dcb0160)}</dd>
      </dl>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Record the references">
        <TextField id="ref-dsa" label="Data sharing agreement" value={dsa} onChange={(v) => { write.fresh(); setDsa(v); }} requirement="optional" />
        <TextField id="ref-dpia" label="Privacy impact assessment" value={dpia} onChange={(v) => { write.fresh(); setDpia(v); }} requirement="optional" />
        <TextField id="ref-dcb" label="Clinical safety case" value={dcb} onChange={(v) => { write.fresh(); setDcb(v); }} requirement="optional" />
        {problem !== '' ? <p className={styles.problem}>{problem}</p> : null}
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={write.busy}>
            Save references
          </Button>
        </div>
      </form>
    </Card>
  );
}

const BINDING_WORD = { pending: 'Waiting to be verified', verified: 'Verified', revoked: 'Replaced' } as const;
const MAPPING_WORD = { active: 'In use', retired: 'Stopped' } as const;

/** The tenant's directory and who gets which role. The organisation binds its directory (or the operator names it
 * when creating the tenant) and it waits; checking the domain and verifying it is the operator's. */
export function DirectoryPanel(props: PanelProps) {
  const write = useWrite(props.tenantId, props);
  const bindings = props.detail.bindings.filter((b) => b.status !== 'revoked');
  const roles = props.detail.roleMappings;
  const waiting = bindings.find((b) => b.status === 'pending');
  return (
    <Card heading="Directory">
      {bindings.length === 0 ? (
        <>
          <p className={styles.text}>The tenant’s administrator has not bound a directory yet.</p>
          <p className={styles.muted}>The organisation’s administrator can bind one on their Users and roles page. You can also name it when you create a tenant.</p>
        </>
      ) : (
        <div className={styles.scroll}>
          <table className={`${styles.table} ${styles.stackTable}`}>
            <caption>Directories</caption>
            <thead>
              <tr>
                <th scope="col">Directory id</th>
                <th scope="col">State</th>
                <th scope="col">Verified</th>
              </tr>
            </thead>
            <tbody>
              {bindings.map((b) => (
                <tr key={b.directoryId}>
                  <td data-label="Directory id">{b.directoryId}</td>
                  <td data-label="State">
                    <span className={b.status === 'verified' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{BINDING_WORD[b.status]}</span>
                  </td>
                  <td data-label="Verified">{whenText(b.verifiedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {waiting !== undefined ? (
        <>
          <p className={styles.text}>Check that the organisation owns the domain, then verify the directory. Nobody can sign in through it until you do.</p>
          <Said say={write.say} />
          <div className={styles.actions}>
            <Button variant="secondary" busy={write.busy} onClick={() => void write.run('POST', 'directory/verification', { directoryId: waiting.directoryId }, () => 'Directory verified.', () => 'The directory could not be verified. Try again.')}>
              Verify this directory
            </Button>
          </div>
        </>
      ) : (
        <Said say={write.say} />
      )}
      {roles.length === 0 ? (
        <p className={styles.muted}>No group is mapped to a role yet. Until one is, nobody can sign in to this tenant.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={`${styles.table} ${styles.stackTable}`}>
            <caption>Roles by group</caption>
            <thead>
              <tr>
                <th scope="col">Group object id</th>
                <th scope="col">Role</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((m) => (
                <tr key={m.groupObjectId}>
                  <td data-label="Group object id">{m.groupObjectId}</td>
                  <td data-label="Role">{roleName(m.role)}</td>
                  <td data-label="State">{MAPPING_WORD[m.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function InvitationPanel(props: PanelProps) {
  const [mobile, setMobile] = useState('');
  const [error, setError] = useState<string | null>(null);
  const write = useWrite(props.tenantId, props);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isUkMobile(mobile)) {
      setError('Enter a UK mobile number, for example 07700 900123.');
      return;
    }
    setError(null);
    void write
      .run('POST', 'admin-invitation', { mobile }, (data) => `Invitation sent. It ends ${whenText(data.expiresAt ?? null)}. The number is not shown again.`, (status) =>
        status === 409 ? 'An invitation is already open for this tenant. Wait for it to end or be used.' : 'The invitation could not be sent. Try again.',
      )
      .then((ok) => {
        if (ok) setMobile('');
      });
  }
  return (
    <Card heading="First administrator">
      <p className={styles.text}>The first administrator is invited by text and signs in with the tenant’s own directory.</p>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Invite the first administrator">
        <TextField id="invite-mobile" label="Mobile number" value={mobile} onChange={(v) => { write.fresh(); setMobile(v); }} requirement="none" inputMode="tel" autoComplete="off" error={error} />
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant="secondary" type="submit" busy={write.busy}>
            Send invitation
          </Button>
        </div>
      </form>
    </Card>
  );
}

type Consent = ReturnType<typeof parseConsent>;
const CONSENT_WORD: Record<string, string> = { pending: 'Waiting for approval', consented: 'Approved', expired: 'Expired', revoked: 'Replaced by a newer invitation' };
const WORK_EMAIL = /^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;

/**
 * Step 1 of admin consent (DEC-1316): the operator names the organisation's Entra administrator, who is emailed a
 * link. The page shows only the masked address and where the invitation stands; the address is never shown or kept
 * in the clear. "Approved" is only ever what the back end confirmed through Microsoft Graph in their directory.
 */
export function ConsentPanel(props: PanelProps) {
  const { state, reload } = useOperatorRead<Consent>(`/api/bff/platform/tenants/${props.tenantId}/admin-consent`);
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const write = useWrite(props.tenantId, props);
  const hasDirectory = props.detail.bindings.some((b) => b.status !== 'revoked');
  const invitation = state.status === 'ok' ? state.data.invitation : null;
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
        () => 'Invitation emailed. It stays valid for 7 days. The address is not shown again.',
        (status) => (status === 403 || status === 404 || status === 409 ? 'The invitation could not be sent. Set the directory first, and check that an email sender is available.' : 'The invitation could not be sent. Try again.'),
      )
      .then((ok) => {
        if (ok) {
          setEmail('');
          reload();
        }
      });
  }
  return (
    <Card heading="Administrator consent">
      <p className={styles.text}>
        The organisation’s Microsoft Entra administrator is emailed a link to approve Overwatch in their own directory. It is marked approved only once Overwatch can be seen installed there.
      </p>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the invitation.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the invitation.
        </p>
      ) : null}
      {invitation === null ? (
        state.status === 'ok' ? <p className={styles.text}>No invitation has been sent.</p> : null
      ) : (
        <dl className={styles.facts} aria-label="Latest invitation">
          <dt>Sent to</dt>
          <dd>{invitation.emailMasked}</dd>
          <dt>State</dt>
          <dd>{CONSENT_WORD[invitation.status] ?? invitation.status}</dd>
          <dt>Sent</dt>
          <dd>{whenText(invitation.createdAt)}</dd>
          <dt>{invitation.status === 'consented' ? 'Approved' : 'Ends'}</dt>
          <dd>{whenText(invitation.status === 'consented' ? invitation.consentedAt : invitation.expiresAt)}</dd>
          {invitation.status === 'pending' && invitation.reason !== null ? (
            <>
              <dt>Not yet</dt>
              <dd>{invitation.reason}</dd>
            </>
          ) : null}
        </dl>
      )}
      {hasDirectory ? (
        <form className={styles.stack} onSubmit={submit} noValidate aria-label="Invite the Entra administrator">
          <TextField id="consent-email" label="Administrator’s work email" value={email} onChange={(v) => { write.fresh(); setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={error} />
          <Said say={write.say} />
          <div className={styles.actions}>
            <Button variant="secondary" type="submit" busy={write.busy}>
              {invitation === null ? 'Send consent invitation' : 'Send again'}
            </Button>
          </div>
        </form>
      ) : (
        <p className={styles.text}>Set the directory first. The consent link is for that directory.</p>
      )}
    </Card>
  );
}
