'use client';

import { useId, useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import r from './Reach.module.css';
import { E164, NUMBER_STATE, Said, StepSection, useWrite, type PanelProps } from './shared';

const TEST_TEXT_FAILED: Record<number, string> = {
  409: 'The organisation’s text account is not set up yet.',
  400: 'The text could not be sent to that number. Check it is a UK mobile number.',
  422: 'The text could not be sent to that number. Check it is a UK mobile number.',
  503: 'The text service is busy. Try again in a moment.',
};

/**
 * Sends one test text from a line to a mobile the operator types, and says what happened in words. `line` is the
 * organisation's own number, or null for the shared line. The mobile is personal data: it is kept only while it is being
 * typed, sent once in the request body, cleared as soon as the text is sent, and never shown again or put in a message.
 */
function TestTextForm({ tenantId, line, lineLabel, first, props }: { tenantId: string; line: string | null; lineLabel: string; first: boolean; props: PanelProps }) {
  const [mobile, setMobile] = useState('');
  const [problem, setProblem] = useState('');
  const write = useWrite(tenantId, props);
  const id = useId();
  function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isUkMobile(mobile)) {
      setProblem('Enter a UK mobile number, like 07700 900456.');
      return;
    }
    setProblem('');
    const body = line === null ? { to: mobile.trim() } : { e164: line, to: mobile.trim() };
    void write
      .run('POST', 'numbers/test-text', body, () => 'Test text sent. This line is now marked as tested because the text provider accepted the text. Overwatch does not wait to see it arrive, so check the phone.', (status) => TEST_TEXT_FAILED[status] ?? 'The test text could not be sent. Try again.')
      .then((ok) => {
        if (ok) setMobile('');
      });
  }
  return (
    <form className={ts.form} onSubmit={send} noValidate aria-label={`Send a test text from ${lineLabel}`}>
      <TextField id={`test-mobile-${id}`} label="Mobile phone to send the test to" value={mobile} onChange={(v) => { write.fresh(); setProblem(''); setMobile(v); }} requirement="none" type="tel" inputMode="tel" autoComplete="off" hint="A UK mobile number. It is used for this one text and is not kept." error={problem === '' ? undefined : problem} />
      <Said say={write.say} />
      <div className={styles.actions}>
        <Button variant={first ? 'primary' : 'secondary'} type="submit" busy={write.busy}>
          Send a test text
        </Button>
      </div>
    </form>
  );
}

/** Stops using one of the organisation's own numbers, after a confirm step. The number stays held by the organisation. */
function StopUsing({ tenantId, e164, props }: { tenantId: string; e164: string; props: PanelProps }) {
  const [asking, setAsking] = useState(false);
  const write = useWrite(tenantId, props);
  if (!asking) {
    return (
      <div className={styles.actions}>
        <Button variant="neutral" ariaLabel={`Stop using ${e164}`} onClick={() => setAsking(true)}>
          Stop using this number
        </Button>
      </div>
    );
  }
  return (
    <div role="group" aria-label={`Stop using ${e164}`} className={ts.confirm}>
      <p className={ts.text}>Stop using {e164}? Texts will no longer be sent from it. The number stays held for this organisation, so no other organisation can take it.</p>
      <Said say={write.say} />
      <div className={styles.actions}>
        <Button variant="secondary" busy={write.busy} onClick={() => void write.run('POST', 'numbers/retire', { e164 }, () => 'The number is no longer in use.', () => 'The number could not be stopped. Try again.').then((ok) => ok && setAsking(false))}>
          Yes, stop using it
        </Button>
        <Button variant="neutral" onClick={() => setAsking(false)}>
          Keep using it
        </Button>
      </div>
    </div>
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
  const sharedWrite = useWrite(props.tenantId, props);
  const shared = props.detail.sharedLine;

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
  // A number counts as tested only while it is in use: a stopped one is held, not working.
  const testedOwn = numbers.some((n) => n.status === 'active' && n.testedAt !== null);
  const testedShared = shared !== null && shared.status === 'active' && shared.testedAt !== null;
  const hostFirst = props.isNext && props.detail.host === null;
  const numberFirst = props.isNext && !hostFirst && numbers.length === 0 && shared === null;
  const testFirst = props.isNext && !hostFirst && !numberFirst;
  return (
    <StepSection
      step={props.step}
      heading={props.heading}
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
      <dl className={r.stands}>
        <div className={r.row}>
          <dt className={r.rowTitle}>Web address</dt>
          <dd className={r.rowTag}>
            <StatusTag variant={props.detail.host === null ? 'todo' : 'done'}>{props.detail.host === null ? 'Address not set' : 'Address set'}</StatusTag>
          </dd>
          <dd className={r.rowDetail}>{props.detail.host === null ? 'No web address is set yet.' : `Their web address is ${props.detail.host}.`}</dd>
        </div>
        <div className={r.row}>
          <dt className={r.rowTitle}>Text number</dt>
          <dd className={r.rowTag}>
            <StatusTag variant={testedOwn || testedShared ? 'done' : 'todo'}>{testedOwn || testedShared ? 'Number tested' : 'Number not tested'}</StatusTag>
          </dd>
          <dd className={r.rowDetail}>{testedOwn ? 'Their own number, test text sent.' : testedShared ? 'Shared line, test text sent. Sending only.' : 'No text number has been tested yet.'}</dd>
        </div>
      </dl>
      <form className={ts.form} onSubmit={saveHost} noValidate aria-label="Set the web address">
        <TextField id="tenant-host" label="Web address" value={host} onChange={(v) => { hostWrite.fresh(); setHost(v); }} requirement="none" hint="What people type to reach Overwatch for this organisation." />
        <Said say={hostWrite.say} />
        <div className={styles.actions}>
          <Button variant={hostFirst ? 'primary' : 'secondary'} type="submit" busy={hostWrite.busy}>
            Save web address
          </Button>
        </div>
      </form>

      <p className={ts.text}>Their text messages are sent from their own number, set up here. Send a test text from it to a mobile phone to check it works.</p>
      {numbers.length === 0 ? (
        <p className={ts.text}>No text number is recorded yet.</p>
      ) : (
        <ul className={ts.lines} aria-label="Text numbers">
          {numbers.map((n) => (
            <li key={n.e164} className={ts.line}>
              <p className={ts.lineHead}>
                <strong>{n.e164}</strong>
                <span> · {NUMBER_STATE[n.status] ?? n.status}</span>
                <span> · {n.testedAt === null ? 'Not tested' : `Tested ${whenText(n.testedAt)}`}</span>
              </p>
              {n.status === 'active' ? (
                <div className={ts.lineActions}>
                  <TestTextForm tenantId={props.tenantId} line={n.e164} lineLabel={n.e164} first={testFirst && n.testedAt === null} props={props} />
                  <StopUsing tenantId={props.tenantId} e164={n.e164} props={props} />
                </div>
              ) : (
                <p className={styles.muted}>This number is held for this organisation, so no other organisation can take it.</p>
              )}
            </li>
          ))}
        </ul>
      )}

      <h4 className={ts.subTitle}>Overwatch’s shared line (sending only)</h4>
      <p className={ts.text}>Until the organisation has its own number, it can send texts from Overwatch’s shared line. Texts can be sent. People cannot reply by text until the organisation has its own number.</p>
      <Said say={sharedWrite.say} />
      {shared === null ? (
        <>
          <div className={styles.actions}>
            <Button variant="secondary" busy={sharedWrite.busy} onClick={() => void sharedWrite.run('POST', 'numbers/shared', {}, () => 'The shared line is set up for sending.', (status) => (status === 409 ? 'The shared line is not available yet. Tell the Overwatch team.' : 'The shared line could not be set up. Try again.'))}>
              Use Overwatch’s shared line (sending only)
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className={ts.lineHead}>
            <strong>Overwatch’s shared line</strong>
            <span> · {NUMBER_STATE[shared.status] ?? shared.status}</span>
            <span> · {shared.testedAt === null ? 'Not tested' : `Tested ${whenText(shared.testedAt)}`}</span>
          </p>
          {shared.status === 'active' ? <TestTextForm tenantId={props.tenantId} line={null} lineLabel="the shared line" first={testFirst && numbers.length === 0 && shared.testedAt === null} props={props} /> : null}
        </>
      )}
      <form className={`${ts.form} ${ts.formGroup}`} onSubmit={record} noValidate aria-label="Record a text number">
        <TextField id="number-e164" label="Text number" value={number} onChange={(v) => { write.fresh(); setNumber(v); }} requirement="none" hint="In international form, with the plus sign." error={errors.number} />
        <TextField id="number-account" label="Text account" value={account} onChange={(v) => { write.fresh(); setAccount(v); }} requirement="none" hint="The account the number belongs to at the text message provider." error={errors.account} />
        <TextField id="number-sender" label="Sender name" value={sender} onChange={(v) => { write.fresh(); setSender(v); }} requirement="none" hint="The name people see the texts come from." error={errors.sender} />
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant={numberFirst ? 'primary' : 'secondary'} type="submit" busy={write.busy}>
            Record text number
          </Button>
        </div>
      </form>
    </StepSection>
  );
}
