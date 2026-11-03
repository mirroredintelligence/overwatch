import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { confirmConsent, type ConsentOutcome } from '@/lib/adminConsent/confirm';
import styles from './page.module.css';

export const metadata: Metadata = {
  title: 'Approve Overwatch - Overwatch',
  robots: { index: false },
};

// Where Microsoft returns an Entra administrator after the admin consent page (DEC-1316). Public: no session.
// The page asks the back end to CONFIRM, through Microsoft Graph in the administrator's own directory, that
// Overwatch is installed there; what the redirect says is never taken as proof, and the `tenant` in the address
// is never read (the tenant is the one the `state` names, checked by the back end). The page names the
// organisation only after the back end has confirmed the invitation, and no one's data.

export const dynamic = 'force-dynamic';

type Search = { state?: string | string[]; admin_consent?: string | string[] };

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function words(outcome: ConsentOutcome): { heading: string; text: string } {
  switch (outcome.kind) {
    case 'consented':
      return {
        heading: 'Overwatch is approved',
        text: `${outcome.organisation ?? 'Your organisation'} can now go ahead with Overwatch. You can close this page.`,
      };
    case 'pending':
      return {
        heading: 'Not approved yet',
        text: 'We could not see Overwatch in your directory yet. Approvals can take a minute to appear. Check again in a moment.',
      };
    case 'expired':
    case 'revoked':
      return {
        heading: 'This link can no longer be used',
        text: 'It has expired or been withdrawn. Ask the person who set up Overwatch to send a new invitation.',
      };
    case 'unavailable':
      return { heading: 'We could not check just now', text: 'Nothing has been changed. Open the link in the email again in a few minutes.' };
    case 'invalid':
      return { heading: 'This link is not valid', text: 'Ask the person who set up Overwatch to send a new invitation.' };
  }
}

export default async function AdminConsentReturnPage({ searchParams }: { searchParams: Promise<Search> }) {
  const query = await searchParams;
  const state = one(query.state);
  const adminConsent = one(query.admin_consent);
  const host = (await headers()).get('host');
  const outcome = await confirmConsent({ state, adminConsent, host });
  const { heading, text } = words(outcome);
  const approved = outcome.kind === 'consented';
  const cardClass = approved ? `${styles.card} ${styles.approved}` : outcome.kind === 'pending' ? `${styles.card} ${styles.pending}` : styles.card;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <p className={styles.brand}>
          <span className={styles.logo} aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
              <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
              <circle cx="13" cy="13" r="4.2" fill="#fff" />
              <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
            </svg>
          </span>
          Overwatch
        </p>
        <section aria-labelledby="consent-heading" className={cardClass} data-el="ADMIN_CONSENT_RETURN" data-outcome={outcome.kind}>
          {approved && (
            <span className={styles.mark} aria-hidden="true">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#0B5C8C" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12.5l4.5 4.5L19 7.5" />
              </svg>
            </span>
          )}
          <h1 id="consent-heading" className={approved ? styles.bigHeading : outcome.kind === 'pending' ? `${styles.heading} ${styles.pendingHeading}` : styles.heading}>
            {heading}
          </h1>
          <p className={approved ? `${styles.text} ${styles.approvedText}` : styles.text} role={approved ? 'status' : undefined}>
            {text}
          </p>
          {approved && (
            <div className={styles.note}>You can review or remove Overwatch&apos;s access at any time in Microsoft Entra, under Enterprise applications.</div>
          )}
          {outcome.kind === 'pending' && state !== undefined && (
            <form action="/admin-consent/return" method="get" className={styles.form}>
              <input type="hidden" name="state" value={state} />
              {adminConsent !== undefined && <input type="hidden" name="admin_consent" value={adminConsent} />}
              <button type="submit" className={styles.again}>
                Check again
              </button>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}
