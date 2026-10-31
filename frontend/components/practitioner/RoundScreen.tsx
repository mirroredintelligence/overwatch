'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { parseShift, type RoundItem } from '@/lib/practitioner/answers';
import { useBffRead } from '@/lib/practitioner/browser';
import { clock } from '@/lib/reporter/times';
import { PhoneScreen, wantedText } from './PhoneScreen';
import styles from './practitioner.module.css';

// Today's round: the visits the person has accepted today, in the order they are wanted, then those that
// are finished. The order is the time each is wanted by and nothing about who does it. Each row is the area
// sector and how far on the visit is; the address is on the visit's own page, once opened.

const STATE_WORD: Record<RoundItem['state'], string> = {
  offered: 'Offered',
  accepted: 'To do',
  'on-my-way': 'On the way',
  arrived: 'Arrived',
  done: 'Done',
  'not-reached': 'Could not reach',
  declined: 'Declined',
  expired: 'Expired',
  withdrawn: 'Withdrawn',
};

export function RoundScreen() {
  const router = useRouter();
  const read = useBffRead('/api/bff/practitioner/shift', parseShift);
  useEffect(() => {
    if (read.kind === 'ended') router.replace('/app/pin');
  }, [read, router]);

  if (read.kind === 'failed') return <PhoneScreen title="Today’s round" backHref="/app/practitioner"><p>We could not load your round. Try again shortly.</p></PhoneScreen>;
  if (read.kind !== 'ready') return <PhoneScreen title="Today’s round" backHref="/app/practitioner"><p role="status">Opening your round</p></PhoneScreen>;
  const { round } = read.value;

  return (
    <PhoneScreen title="Today’s round" backHref="/app/practitioner">
      <h1 className={styles.title}>Today’s round</h1>
      {round.length === 0 ? (
        <p>No visits yet today.</p>
      ) : (
        <ul className={styles.list} aria-label="Today’s visits">
          {round.map((item) => (
            <li key={item.id}>
              <a className={styles.item} href={`/app/practitioner/visits/${encodeURIComponent(item.id)}`} data-el="PRAC-ROUND-VISIT-LINK">
                <span className={styles.itemText}>
                  <strong>{item.dueBy === null ? `Sector ${item.sector}` : `${clock(item.dueBy)}, sector ${item.sector}`}</strong>
                  <span className={styles.itemMeta}>{wantedText(item.wantedWithin)}</span>
                </span>
                <span>{STATE_WORD[item.state]}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </PhoneScreen>
  );
}
