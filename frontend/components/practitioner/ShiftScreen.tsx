'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { StatusTag } from '@/components/ui/StatusTag';
import { parseSettings, parseShift, SHIFT_STATUSES, type Shift, type ShiftStatus } from '@/lib/practitioner/answers';
import { useBffRead } from '@/lib/practitioner/browser';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import { PhoneFailed, PhoneOpening, PhoneScreen, wantedText } from './PhoneScreen';
import styles from './practitioner.module.css';

// My shift (RadarPhone 1): a greeting, the optional status, today's visits and the next one, the offers
// waiting, and the way to the round and to the location choice. The status is optional and is never used
// to time or rank anyone: it is a word the person sets (and clears) for themselves and the coordinator.

const STATUS_LABEL: Record<ShiftStatus, string> = {
  available: 'Available',
  'on-a-visit': 'On a visit',
  break: 'Break',
  'off-shift': 'Off shift',
};

export function greeting(hour: number): string {
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function nextLine(next: NonNullable<Shift['next']>): string {
  return next.dueBy === null ? `Next: sector ${next.sector}, ${next.wantedWithin}` : `Next: ${clock(next.dueBy)}, sector ${next.sector}`;
}

export function ShiftScreen() {
  const router = useRouter();
  const read = useBffRead('/api/bff/practitioner/shift', parseShift);
  // What the person has set on this screen; until they set something, what the back end holds.
  const [set, setSet] = useState<{ status: ShiftStatus | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (read.kind === 'ended') router.replace('/app/pin');
  }, [read, router]);

  if (read.kind === 'failed') return <PhoneFailed title="My shift" backHref="/app">We could not load your shift. Try again shortly.</PhoneFailed>;
  if (read.kind !== 'ready') return <PhoneOpening title="My shift" backHref="/app" label="Opening your shift." />;
  const shift = read.value;
  const status = set === null ? shift.status : set.status;

  const choose = async (next: ShiftStatus | null) => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    const reply = await bffRequest('/api/bff/practitioner/settings', { method: 'PUT', body: { status: next } });
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const saved = reply.status === 200 ? parseSettings(reply.body) : null;
    if (saved === null) return setFailed(true);
    setSet({ status: saved.status });
    return undefined;
  };

  return (
    <PhoneScreen
      title="My shift"
      backHref="/app"
      actions={
        <>
          <Button variant="primary" href="/app/practitioner/round" dataEl="PRAC-SHIFT-ROUND-BTN">
            See today’s round
          </Button>
          <Button variant="secondary" href="/app/practitioner/location" dataEl="PRAC-SHIFT-LOCATION-BTN">
            Share location during visits
          </Button>
        </>
      }
    >
      <h1 className={styles.title}>{greeting(new Date().getHours())}</h1>

      <div className={styles.group} role="group" aria-label="Status">
        <div className={styles.labelRow}>
          <p className={styles.label}>Status</p>
          <span className={styles.optional}>Optional</span>
        </div>
        <div className={styles.chips}>
          {SHIFT_STATUSES.map((word) => (
            <Chip key={word} pressed={status === word} disabled={busy} onPressedChange={(on) => void choose(on ? word : null)} dataEl={`PRAC-SHIFT-STATUS-${word.toUpperCase()}`}>
              {STATUS_LABEL[word]}
            </Chip>
          ))}
        </div>
        {failed ? <Banner tone="warning" title="We could not save that. Try again." /> : null}
      </div>

      {shift.offers.length === 0 ? null : (
        <div className={styles.group} role="group" aria-label="New offers">
          {shift.offers.length > 1 ? <p className={styles.label}>{`${shift.offers.length} new offers`}</p> : null}
          <ul className={styles.list}>
            {shift.offers.map((offer) => (
              <li key={offer.id}>
                <a className={`${styles.card} ${styles.offerCard}`} href={`/app/practitioner/offers/${encodeURIComponent(offer.id)}`} data-el="PRAC-SHIFT-OFFER-LINK">
                  <StatusTag variant="live">{shift.offers.length === 1 ? '1 new offer' : 'New offer'}</StatusTag>
                  <strong className={styles.cardTitle}>{offer.need}</strong>
                  <span className={styles.cardMeta}>{`Sector ${offer.sector} · ${wantedText(offer.wantedWithin).replace(/^Wanted /, '').toLowerCase()}`}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.card} data-el="PRAC-SHIFT-TODAY">
        {shift.visitsToday === 0 ? (
          <p className={styles.panelTitle}>Today: no visits yet</p>
        ) : (
          <>
            <p className={styles.panelTitle}>{shift.visitsToday === 1 ? 'Today: 1 visit' : `Today: ${shift.visitsToday} visits`}</p>
            {shift.next === null ? <p>Nothing waiting to start.</p> : <p>{nextLine(shift.next)}</p>}
          </>
        )}
      </div>

      <p className={styles.note}>{shift.location === 'travel' ? 'You share an estimated arrival, only while you travel to a visit.' : 'Your location is not shared unless you turn it on for a visit.'}</p>
    </PhoneScreen>
  );
}
