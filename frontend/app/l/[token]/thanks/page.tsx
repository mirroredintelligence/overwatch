import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import { londonHm, parseThanks } from '@/lib/links/model';
import styles from '@/components/reporter/Reporter.module.css';

// The thank-you page after a figure is recorded. It shows the answer the link page carried here
// (the service, the figure, the time it was recorded and the next update). It holds no token
// check: the figure is already recorded, and it says nothing a link could be used for.

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Thank you',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

type Props = {
  params: Promise<{ token: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function ThanksPage({ searchParams }: Props) {
  const raw = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === 'string') query.set(key, value);
  }
  const detail = parseThanks(query);

  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>DIUCS capacity update</p>
      <h1 className={styles.title}>Thank you</h1>
      {detail !== null ? (
        <p className={styles.question}>
          {`${detail.serviceName}: ${detail.value} ${detail.unitLabel}, recorded at ${londonHm(detail.recordedAt)}.`}
        </p>
      ) : null}
      {detail?.nextDue ? <p className={styles.or}>{`Next update due ${londonHm(detail.nextDue)}`}</p> : null}
      <Button variant="neutral" href="/sign-in" dataEl="REP-LINK-BOARD-LINK">
        See the live board
      </Button>
      <p className={styles.footer}>You can close this page.</p>
    </main>
  );
}
