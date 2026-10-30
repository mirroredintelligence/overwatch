'use client';

import { useCallback, useEffect, useState } from 'react';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { REFRESH_EVENTS } from '@/lib/board/useBoardFeed';
import { dateTimeLine, servicesWord } from '@/lib/lead/format';
import { leadGet, leadPost } from '@/lib/lead/browser';
import { parseOverview } from '@/lib/lead/parse';
import type { LeadOverview as Overview } from '@/lib/lead/types';
import { ChaseCard } from './ChaseCard';
import { CoveringList } from './CoveringList';
import { OldFigureCard } from './OldFigureCard';
import { SystemCounts } from './SystemCounts';
import styles from './Lead.module.css';

// The shift lead's main page (W17). It reads the overview from the BFF on load, every 60 seconds and on
// a board update, and never shows an empty list for a read that failed (H-330). A failed read keeps the
// last good overview on screen and says that it could not be loaded.

const REFRESH_MS = 60_000;
const STREAM_URL = '/api/bff/events';
const OVERVIEW_URL = '/api/bff/lead/overview';
const MINUTE_MS = 60_000;

type Load = { kind: 'loading' } | { kind: 'ready'; overview: Overview } | { kind: 'failed' };

function remindPath(serviceId: string): string {
  return `/api/bff/lead/services/${encodeURIComponent(serviceId)}/remind`;
}

export function LeadOverview() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [now, setNow] = useState<number>(() => Date.now());
  const [notice, setNotice] = useState<string>('');
  const [noticeFailed, setNoticeFailed] = useState(false);
  const [phoned, setPhoned] = useState<{ serviceName: string } | null>(null);

  const reload = useCallback(async () => {
    try {
      const overview = parseOverview(await leadGet(OVERVIEW_URL));
      setLoad({ kind: 'ready', overview });
    } catch {
      // Keep the last good overview, if there is one. A failed read is never an empty list.
      setLoad((previous) => (previous.kind === 'ready' ? previous : { kind: 'failed' }));
    }
  }, []);

  useEffect(() => {
    // The first read is started by the interval's first tick and by the stream, not synchronously
    // here: a read that answers at once would otherwise set state inside this effect's body.
    const first = setTimeout(() => void reload(), 0);
    const timer = setInterval(() => void reload(), REFRESH_MS);
    const clock = setInterval(() => setNow(Date.now()), MINUTE_MS);
    let stream: EventSource | null = null;
    if (typeof EventSource !== 'undefined') {
      stream = new EventSource(STREAM_URL);
      for (const name of REFRESH_EVENTS) stream.addEventListener(name, () => void reload());
    }
    return () => {
      clearTimeout(first);
      clearInterval(timer);
      clearInterval(clock);
      stream?.close();
    };
  }, [reload]);

  async function remind(serviceId: string) {
    setNotice('');
    const result = await leadPost(remindPath(serviceId));
    if (result.ok) {
      setNoticeFailed(false);
      setNotice('Reminder sent');
    } else {
      setNoticeFailed(true);
      setNotice('The reminder could not be sent. Try again.');
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>DIUCS capacity · Shift lead</h1>
        <time className={styles.muted} dateTime={new Date(now).toISOString()}>
          {dateTimeLine(now)}
        </time>
      </header>

      {load.kind === 'failed' ? (
        <p role="alert" className={styles.line}>
          We could not load the shift lead page. Try again shortly.
        </p>
      ) : null}

      {load.kind === 'loading' ? <p className={styles.muted}>Loading the services to chase.</p> : null}

      {load.kind === 'ready' ? (
        <>
          <section aria-labelledby="lead-chase-heading" data-el="LEAD-CHASE">
            {load.overview.chasing.length === 0 ? (
              <>
                <h2 id="lead-chase-heading" className={styles.sectionHeading}>
                  Chasing
                </h2>
                <p className={styles.line}>No services need chasing.</p>
              </>
            ) : (
              <>
                <h2 id="lead-chase-heading" className={styles.sectionHeading}>
                  {`${load.overview.chasing.length} ${servicesWord(load.overview.chasing.length)} need chasing`}
                </h2>
                <div className={styles.stack}>
                  {load.overview.chasing.map((item) => (
                    <ChaseCard
                      key={item.serviceId}
                      item={item}
                      onEnterPhoned={() => setPhoned({ serviceName: item.name })}
                      onRemind={() => void remind(item.serviceId)}
                    />
                  ))}
                </div>
              </>
            )}
          </section>

          {load.overview.gettingOld.length > 0 ? (
            <section className={styles.section} aria-labelledby="lead-old-heading" data-el="LEAD-OLD">
              <h2 id="lead-old-heading" className={styles.sectionHeading}>
                Getting old
              </h2>
              <div className={styles.stack}>
                {load.overview.gettingOld.map((item) => (
                  <OldFigureCard
                    key={item.serviceId}
                    item={item}
                    now={now}
                    onAsk={() => void remind(item.serviceId)}
                  />
                ))}
              </div>
            </section>
          ) : null}

          <CoveringList items={load.overview.covering} />
          <SystemCounts counts={load.overview.counts} reportingToday={load.overview.reportingToday} />
        </>
      ) : null}

      <p role="status" className={noticeFailed ? styles.muted : styles.line} data-failed={noticeFailed || undefined}>
        {notice}
      </p>

      <LeadPhonedDialog
        open={phoned !== null}
        serviceName={phoned?.serviceName ?? ''}
        onClose={() => setPhoned(null)}
      />
    </main>
  );
}
