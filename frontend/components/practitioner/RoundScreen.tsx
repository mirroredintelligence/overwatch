'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { parseShift, type RoundItem } from '@/lib/practitioner/answers';
import { useBffRead } from '@/lib/practitioner/browser';
import { clock } from '@/lib/reporter/times';
import { PhoneFailed, PhoneOpening, PhoneScreen, whenText } from './PhoneScreen';
import styles from './practitioner.module.css';

// Today's round: the visits the person has accepted today, in the order they are wanted: the next one, the
// later ones, and (collapsed) those that are finished. The order is the one the back end gives and nothing about
// who does it. Each row is the area sector and how far on the visit is; the address is on the visit's own
// page, once opened.

const STATE_TAG: Record<RoundItem['state'], { word: string; variant: StatusTagVariant }> = {
  offered: { word: 'Offered', variant: 'due' },
  accepted: { word: 'Accepted', variant: 'confirmed' },
  'on-my-way': { word: 'On the way', variant: 'live' },
  arrived: { word: 'Arrived', variant: 'live' },
  done: { word: 'Done', variant: 'done' },
  'not-reached': { word: 'Could not reach', variant: 'problem' },
  declined: { word: 'Declined', variant: 'closed' },
  expired: { word: 'Expired', variant: 'closed' },
  withdrawn: { word: 'Withdrawn', variant: 'closed' },
};

const FINISHED: readonly RoundItem['state'][] = ['done', 'not-reached', 'declined', 'expired', 'withdrawn'];

function Visit({ item, current }: { item: RoundItem; current?: boolean }) {
  const tag = STATE_TAG[item.state];
  return (
    <li>
      <a className={`${styles.visit} ${current === true ? styles.visitNext : ''}`} href={`/app/practitioner/visits/${encodeURIComponent(item.id)}`} data-el="PRAC-ROUND-VISIT-LINK">
        <span className={styles.itemText}>
          <strong className={styles.visitTitle}>{item.dueBy === null ? `Sector ${item.sector}` : `${clock(item.dueBy)} · sector ${item.sector}`}</strong>
          <span className={styles.itemMeta}>{whenText(item.wantedWithin)}</span>
        </span>
        <StatusTag variant={tag.variant}>{tag.word}</StatusTag>
      </a>
    </li>
  );
}

export function RoundScreen() {
  const router = useRouter();
  const read = useBffRead('/api/bff/practitioner/shift', parseShift);
  const [doneOpen, setDoneOpen] = useState(false);
  useEffect(() => {
    if (read.kind === 'ended') router.replace('/app/pin');
  }, [read, router]);

  if (read.kind === 'failed') return <PhoneFailed title="Today’s round" backHref="/app/practitioner">We could not load your round. Try again shortly.</PhoneFailed>;
  if (read.kind !== 'ready') return <PhoneOpening title="Today’s round" backHref="/app/practitioner" label="Opening your round." />;
  const { round } = read.value;
  const open = round.filter((item) => !FINISHED.includes(item.state));
  const finished = round.filter((item) => FINISHED.includes(item.state));
  const [next, ...later] = open;

  return (
    <PhoneScreen title="Today’s round" backHref="/app/practitioner">
      <h1 className={styles.srOnly}>Today’s round</h1>
      {round.length === 0 ? <p className={styles.panel}>No visits yet today.</p> : null}
      {next === undefined ? null : (
        <>
          <h2 className={styles.kicker}>Next</h2>
          <ul className={styles.list} aria-label="Next">
            <Visit item={next} current />
          </ul>
        </>
      )}
      {later.length === 0 ? null : (
        <>
          <h2 className={styles.kicker}>Later</h2>
          <ul className={styles.list} aria-label="Later">
            {later.map((item) => (
              <Visit key={item.id} item={item} />
            ))}
          </ul>
        </>
      )}
      {next === undefined && finished.length > 0 ? <p className={styles.panel}>Nothing left to do today.</p> : null}
      {finished.length === 0 ? null : (
        <Disclose open={doneOpen} onToggle={() => setDoneOpen((was) => !was)} title={`Done today (${finished.length})`}>
          <ul className={styles.list} aria-label="Done today">
            {finished.map((item) => (
              <Visit key={item.id} item={item} />
            ))}
          </ul>
        </Disclose>
      )}
    </PhoneScreen>
  );
}
