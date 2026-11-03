import type { Metadata } from 'next';
import styles from '@/components/reporter/CapacityLink.module.css';
import { LinkFrame } from '@/components/reporter/parts/LinkFrame';
import { londonHm } from '@/lib/links/model';
import { unsealThanks } from '@/lib/links/thanks';

// The thank-you page after a figure is recorded (artboard B1, board 3). Its address holds no link token (the
// link is spent, KI-179) and the detail it shows is sealed by the BFF: the service, the figure, the time it
// was recorded and the next update. An address with no sealed detail, or one made by hand, says thank you and
// nothing about what was recorded. The figure is read-only here. "Change it" is not offered: the address has
// no link to change it with (see the unit report).

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
  // The detail is a courtesy: the page is true without it. A secret that cannot be read (unsealThanks throws then)
  // is logged by name and the page says only thank you; nothing is claimed and nothing is passed.
  const detail = await unsealThanks(sealed).catch(() => {
    console.warn('The thank-you detail could not be opened.');
    return null;
  });

  return (
    <LinkFrame noLoginTag={false}>
      <main className={styles.stack}>
        <section className={`${styles.card} ${styles.cardStart}`}>
          <div className={styles.tick} aria-hidden="true" data-el="REP-LINK-THANKS-MARK" data-tone="done">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" focusable="false">
              <path d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
          </div>
          <h1 className={styles.heading}>Thank you</h1>
          {detail !== null ? (
            <>
              <p className={styles.figureRow}>
                <span className={styles.figure} data-figure={String(detail.value)}>
                  {detail.value}
                </span>
                <span className={styles.unit}>{detail.unitLabel}</span>
              </p>
              <p className={styles.body}>{`${detail.serviceName}, recorded at ${londonHm(detail.recordedAt)}.`}</p>
            </>
          ) : null}
          {detail?.nextDue ? (
            <span className={`${styles.tag} ${styles.tagTint}`} data-el="REP-LINK-NEXT-DUE">{`Next update due ${londonHm(detail.nextDue)}`}</span>
          ) : null}
        </section>
        <a className={`${styles.btn} ${styles.dashed} ${styles.plain}`} href="/sign-in" data-el="REP-LINK-BOARD-LINK">
          See the live board
        </a>
        <p className={styles.noteLarge}>You can close this page.</p>
      </main>
    </LinkFrame>
  );
}
