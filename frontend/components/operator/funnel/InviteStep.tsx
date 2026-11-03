'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import { Said, StepSection, WORK_EMAIL, useWrite, type PanelProps } from './shared';

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
        (status) => (status === 403 || status === 404 || status === 409 ? 'The link could not be sent. Connect their Microsoft work accounts first, and check that Overwatch can send email.' : 'The link could not be sent. Try again.'),
      )
      .then((ok) => {
        if (ok) setEmail('');
      });
  }
  return (
    <StepSection
      step={props.step}
      heading={props.heading}
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
      <p className={ts.text}>
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
          <p className={ts.text}>No approval link has been sent yet.</p>
        ) : invitation.status === 'consented' ? (
          <p className={styles.ok}>{`Approved on ${whenText(invitation.consentedAt)}. Their administrator has approved Overwatch.`}</p>
        ) : invitation.status === 'expired' ? (
          <p className={styles.problem}>The approval link has expired. Send a new one.</p>
        ) : (
          <p className={ts.text}>{`${CONSENT_WORD[invitation.status] ?? 'Waiting for approval'}. The link went to ${invitation.emailMasked} and works until ${whenText(invitation.expiresAt)}.`}</p>
        )
      ) : null}
      {invitation?.status === 'consented' ? null : hasSignIn ? (
        <form className={ts.form} onSubmit={submit} noValidate aria-label="Send the approval link">
          <TextField id="consent-email" label="Their administrator’s work email" value={email} onChange={(v) => { write.fresh(); setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={error} />
          <Said say={write.say} />
          <div className={styles.actions}>
            <Button variant={props.isNext && invitation?.status !== 'pending' ? 'primary' : 'secondary'} type="submit" busy={write.busy}>
              {invitation === null ? 'Send the approval link to their administrator' : 'Send the link again'}
            </Button>
          </div>
        </form>
      ) : (
        <p className={ts.text}>Connect their Microsoft work accounts first. The approval link is for their Microsoft account.</p>
      )}
    </StepSection>
  );
}
