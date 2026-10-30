import styles from '@/components/reporter/setup/Setup.module.css';

// The end of the text or email set-up (W33). Short by design: the reporter is told when they will
// be contacted, and nothing else.

export default async function SetupDonePage({
  searchParams,
}: {
  searchParams: Promise<{ channel?: string }>;
}) {
  await searchParams;
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>You are set up</h1>
      <p>We will contact you at your usual time.</p>
    </main>
  );
}
