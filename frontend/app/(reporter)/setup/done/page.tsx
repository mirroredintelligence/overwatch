import { ProviderShell } from '@/components/provider/ProviderShell';
import styles from './Done.module.css';

// The end of the text or email set-up (W33; board States "Phone · set up by text or email"). Short by design:
// the reporter is told when they will be contacted, and nothing else. There is no session on this page (the
// link is the credential), so the time of the next contact is not shown: the summary needs a session.

export default async function SetupDonePage({
  searchParams,
}: {
  searchParams: Promise<{ channel?: string }>;
}) {
  const { channel } = await searchParams;
  return (
    <ProviderShell>
      <section className={styles.card}>
        <div className={styles.mark} aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </div>
        <h1 className={styles.title}>You are set up</h1>
        <p className={styles.text}>We will contact you at your usual time.</p>
        {channel === 'text' ? <p className={styles.text}>Reply with your number.</p> : null}
        <p className={styles.text}>There is nothing else to do.</p>
      </section>
    </ProviderShell>
  );
}
