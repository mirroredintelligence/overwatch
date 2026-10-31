import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import { londonHm } from '@/lib/links/model';
import { unsealThanks } from '@/lib/links/thanks';
import styles from '@/components/reporter/Reporter.module.css';

// The thank-you page after a figure is recorded. Its address holds no link token (the link is spent,
// KI-179) and the detail it shows is sealed by the BFF: the service, the figure, the time it was recorded
// and the next update. An address with no sealed detail, or one made by hand, says thank you and nothing
// about what was recorded.

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Thank you',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function ThanksPage({ searchParams }: Props) {
  const raw = (await searchParams).d;
  const sealed = typeof raw === 'string' ? raw : '';
  const detail = await unsealThanks(sealed);

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
