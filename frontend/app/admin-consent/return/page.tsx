import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { confirmConsent, type ConsentOutcome } from '@/lib/adminConsent/confirm';
import styles from '../../sign-in/page.module.css';

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
      return { heading: 'Not approved yet', text: outcome.reason };
    case 'expired':
    case 'revoked':
      return { heading: 'This link can no longer be used', text: outcome.reason };
    case 'unavailable':
      return { heading: 'We could not check just now', text: 'Nothing has been changed. Please open the link in the email again in a few minutes.' };
    case 'invalid':
      return { heading: 'This link is not valid', text: 'Ask the person who set up Overwatch to send a new invitation.' };
  }
}

export default async function AdminConsentReturnPage({ searchParams }: { searchParams: Promise<Search> }) {
  const query = await searchParams;
  const host = (await headers()).get('host');
  const outcome = await confirmConsent({ state: one(query.state), adminConsent: one(query.admin_consent), host });
  const { heading, text } = words(outcome);
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <p className={styles.product}>Overwatch</p>
        <section className={styles.card} aria-labelledby="consent-heading" data-el="ADMIN_CONSENT_RETURN">
          <h1 id="consent-heading" className={styles.heading}>
            {heading}
          </h1>
          <p className={styles.text} role={outcome.kind === 'consented' ? 'status' : undefined}>
            {text}
          </p>
        </section>
      </div>
    </main>
  );
}
