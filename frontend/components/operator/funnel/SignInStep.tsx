'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import parts from './Parts.module.css';
import { Said, StepSection, useWrite, type PanelProps } from './shared';

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
    <StepSection
      step={props.step}
      heading={props.heading}
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
      <p className={ts.text}>People at the organisation sign in to Overwatch with their Microsoft work accounts. Overwatch needs to know which Microsoft account is theirs.</p>
      {confirmed !== undefined ? (
        <div className={parts.row} data-state="done">
          <span className={parts.mark} aria-hidden="true">
            ●
          </span>
          <div className={parts.rowBody}>
            <b className={parts.rowTitle}>Microsoft work accounts connected</b>
            <p className={parts.rowSub}>{`Connected to ${name}’s Microsoft accounts.`}</p>
            <p className={parts.rowSub}>{`Confirmed on ${whenText(confirmed.verifiedAt)}`}</p>
          </div>
          <StatusTag variant="done">Done</StatusTag>
        </div>
      ) : waiting !== undefined ? (
        <>
          <div className={parts.row} data-state="waiting">
            <span className={parts.mark} aria-hidden="true">
              ◐
            </span>
            <div className={parts.rowBody}>
              <b className={parts.rowTitle}>Microsoft work accounts named</b>
              <p className={parts.rowSub}>{`A Microsoft account has been named for ${name}. Check that it is theirs, then confirm it. Nobody can sign in with it until you do.`}</p>
            </div>
            <StatusTag variant="waiting">Waiting for you</StatusTag>
          </div>
          <Said say={write.say} />
          <div className={styles.actions}>
            <Button variant={props.isNext ? 'primary' : 'secondary'} busy={write.busy} onClick={() => void write.run('POST', 'directory/verification', { directoryId: waiting.directoryId }, () => 'Confirmed. Their people can now sign in with their Microsoft work accounts.', () => 'It could not be confirmed. Try again.')}>
              Confirm this is their Microsoft account
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className={parts.row} data-state="todo">
            <span className={parts.mark} aria-hidden="true">
              ○
            </span>
            <div className={parts.rowBody}>
              <b className={parts.rowTitle}>Microsoft work accounts not connected</b>
              <p className={parts.rowSub}>No Microsoft account is connected yet.</p>
            </div>
            <StatusTag variant="todo">To do</StatusTag>
          </div>
          <p className={styles.muted}>Their administrator can connect it from the Users and roles page in their own Overwatch. You can check which account an email domain belongs to below.</p>
        </>
      )}
      <details className={ts.disclosure}>
        <summary>Check an email domain</summary>
        <div className={ts.disclosureBody}>
          <form className={ts.form} onSubmit={(event) => void look(event)} noValidate aria-label="Find their Microsoft account">
            <TextField id="signin-domain" label="Their email domain" value={domain} onChange={setDomain} requirement="optional" hint="For example example.nhs.uk. This only looks; it saves nothing." autoComplete="off" dataEl="OP-TENANT-DOMAIN-INPUT" />
            <div className={styles.actions}>
              <Button variant="neutral" type="submit" dataEl="OP-TENANT-DOMAIN-LOOKUP-BTN">
                Look up their Microsoft account
              </Button>
            </div>
          </form>
          {lookup === 'not-valid' ? (
            <p role="status" className={ts.text}>
              Enter a domain name, for example example.nhs.uk.
            </p>
          ) : lookup !== null ? (
            <div className={styles.panel} data-el="OP-TENANT-DOMAIN-CARD" role="status">
              {lookup.directoryId === null ? (
                <p className={ts.text}>{`No Microsoft account was found for ${lookup.domain}. Ask the organisation which one they use.`}</p>
              ) : (
                <>
                  <p className={ts.text}>{`Found a Microsoft account for ${lookup.domain}.`}</p>
                  <p className={ts.text}>
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
        </div>
      </details>
    </StepSection>
  );
}
