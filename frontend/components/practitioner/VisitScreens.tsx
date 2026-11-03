'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { StatusTag } from '@/components/ui/StatusTag';
import { ACTIVE_STATES, parseAnswer, parseVisit, PRACTITIONER_STATUSES, type PractitionerStatus, type Visit, type VisitState } from '@/lib/practitioner/answers';
import { secondsLeft, useBffRead } from '@/lib/practitioner/browser';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import { PhoneFailed, PhoneOpening, PhoneScreen, whenText } from './PhoneScreen';
import styles from './VisitScreens.module.css';

// The visit offer and the accepted visit (RadarPhone 2 and 3, B11), one resource at two stages. An offer shows
// what is needed, the area as a postcode SECTOR, when it is wanted by and how long the offer lasts; the
// address and contact appear only after it is accepted, and only to the person it was offered to. The
// accepted visit takes the status list. Both routes (`/offers/[id]` and `/visits/[id]`) show whichever
// stage the visit is at, so a link to either is never wrong. An estimated arrival is only ever a number of
// minutes the person chooses: the phone's position is never read or sent.

const STATUS_LABEL: Record<PractitionerStatus, string> = {
  'on-my-way': 'On my way',
  arrived: 'Arrived',
  done: 'Visit done',
  'not-reached': 'Could not reach the patient',
};
const ETA_CHOICES = [10, 20, 30, 45, 60] as const;
const SHIFT = '/app/practitioner';
const PIN = '/app/pin';

const CLOSED_TEXT: Partial<Record<VisitState, { title: string; text: string }>> = {
  done: { title: 'Visit done', text: 'Thank you. The details of this visit have been removed from the app.' },
  'not-reached': { title: 'Could not reach the patient', text: 'The coordination team has been told. The details of this visit have been removed from the app.' },
  declined: { title: 'Offer declined', text: 'You declined this offer. Your colleagues’ offers are not affected.' },
  expired: { title: 'Offer expired', text: 'The time to answer this offer has passed.' },
  withdrawn: { title: 'No longer open', text: 'This visit was taken by a colleague, or the booking was cancelled.' },
};

/** Seconds as the offer's clock face, "08:42": two digits each, so the figure keeps its width as it counts. */
function clockFace(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`;
}

function Closed({ state }: { state: VisitState }) {
  const text = CLOSED_TEXT[state] ?? { title: 'No longer open', text: 'This visit is no longer open.' };
  return (
    <PhoneScreen title="Visit" backHref={SHIFT} actions={<Button variant="primary" href={SHIFT} dataEl="PRAC-CLOSED-SHIFT-BTN">Back to my shift</Button>}>
      <div className={`${styles.card} ${styles.closed}`}>
        <StatusTag variant="closed">Closed</StatusTag>
        <h1 className={styles.closedTitle}>{text.title}</h1>
        <p className={styles.closedText}>{text.text}</p>
      </div>
    </PhoneScreen>
  );
}

function OfferView({ visit, onChanged }: { visit: Visit; onChanged: () => void }) {
  const router = useRouter();
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [acceptKey] = useState(() => crypto.randomUUID());
  const [declineKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const left = secondsLeft(visit.expiresAt, now);
  if (left === 0) return <Closed state="expired" />;

  const answer = async (what: 'accept' | 'decline') => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    const reply = await bffRequest(`/api/bff/practitioner/visits/${encodeURIComponent(visit.id)}/${what}`, {
      method: 'POST',
      body: {},
      headers: { 'Idempotency-Key': what === 'accept' ? acceptKey : declineKey },
    });
    setBusy(false);
    if (reply.status === 401) return router.replace(PIN);
    // Taken meanwhile (a colleague accepted, or the time ran out): show what the back end holds now.
    if (reply.status === 409) return onChanged();
    if (reply.status === 200 && parseAnswer(reply.body) !== null) {
      // On the visit's own path (a link to it while it was still an offer) the address does not change, so the
      // visit is read again as well as the person being taken to its path.
      onChanged();
      return router.replace(what === 'accept' ? `${SHIFT}/visits/${encodeURIComponent(visit.id)}` : SHIFT);
    }
    return setFailed(true);
  };

  return (
    <PhoneScreen
      title="Visit offer"
      backHref={SHIFT}
      actions={
        <>
          <Button variant="primary" busy={busy} dataEl="PRAC-OFFER-ACCEPT-BTN" onClick={() => void answer('accept')}>
            Accept visit
          </Button>
          <Button variant="neutral" busy={busy} dataEl="PRAC-OFFER-DECLINE-BTN" onClick={() => void answer('decline')}>
            Decline
          </Button>
        </>
      }
    >
      <StatusTag variant="live">New offer</StatusTag>
      <h1 className={styles.heading}>{visit.need}</h1>
      <dl className={`${styles.card} ${styles.facts}`} data-el="PRAC-OFFER-FACTS">
        <div className={styles.fact}>
          <dt>Area</dt>
          <dd>{visit.sector}</dd>
        </div>
        <div className={styles.fact}>
          <dt>Wanted</dt>
          <dd>{whenText(visit.wantedWithin)}</dd>
        </div>
        {visit.fitsMinutes === null ? null : (
          <div className={styles.fact}>
            <dt>Fits your round</dt>
            <dd>{`+${visit.fitsMinutes} min to your next visit`}</dd>
          </div>
        )}
        <div className={styles.fact}>
          <dt>Offer expires in</dt>
          <dd className={styles.countdown} data-el="PRAC-OFFER-COUNTDOWN">
            {clockFace(left)}
          </dd>
        </div>
      </dl>
      <p className={styles.note}>The address and contact appear only after you accept.</p>
      {failed ? <Banner tone="warning" title="We could not send that. Try again." /> : null}
    </PhoneScreen>
  );
}

function mapsLink(address: string): string {
  return `geo:0,0?q=${encodeURIComponent(address)}`;
}

function ActiveView({ visit, onChanged }: { visit: Visit; onChanged: () => void }) {
  const router = useRouter();
  const [choice, setChoice] = useState<PractitionerStatus | null>(null);
  const [eta, setEta] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState<PractitionerStatus | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const sharing = visit.location === 'travel';

  const update = async () => {
    if (busy || choice === null) return;
    setBusy(true);
    setFailed(false);
    const body = choice === 'on-my-way' && sharing && eta !== null ? { status: choice, etaMinutes: eta } : { status: choice };
    const reply = await bffRequest(`/api/bff/practitioner/visits/${encodeURIComponent(visit.id)}/status`, { method: 'POST', body, headers: { 'Idempotency-Key': key } });
    setBusy(false);
    if (reply.status === 401) return router.replace(PIN);
    if (reply.status === 409) return onChanged();
    if (reply.status === 200 && parseAnswer(reply.body) !== null) {
      setSaved(choice);
      setKey(crypto.randomUUID());
      return onChanged();
    }
    return setFailed(true);
  };

  return (
    <PhoneScreen
      title="Visit accepted"
      backHref={SHIFT}
      actions={
        <Button variant="primary" busy={busy} disabled={choice === null} dataEl="PRAC-VISIT-UPDATE-BTN" onClick={() => void update()}>
          Update status
        </Button>
      }
    >
      <h1 className={`${styles.heading} ${styles.headingSmall}`}>{`Visit ${visit.reference}`}</h1>
      <div className={`${styles.card} ${styles.details}`} data-el="PRAC-VISIT-DETAILS">
        {visit.address === undefined || visit.contact === undefined ? (
          <p>They could not be shown here. Phone the coordination team.</p>
        ) : (
          <>
            <p className={styles.address}>{visit.address}</p>
            <p className={styles.contact}>{`Contact: ${visit.contact}`}</p>
          </>
        )}
        {visit.etaAt === null ? null : <p className={styles.contact}>{`Estimated arrival shared: ${clock(visit.etaAt)}.`}</p>}
        <div className={styles.mapsRow}>
          {visit.address === undefined ? (
            <Button variant="secondary" disabled dataEl="PRAC-VISIT-MAPS-BTN">
              Open in maps
            </Button>
          ) : (
            <Button variant="secondary" href={mapsLink(visit.address)} dataEl="PRAC-VISIT-MAPS-BTN">
              Open in maps
            </Button>
          )}
        </div>
      </div>

      <div className={styles.statuses} role="radiogroup" aria-label="Visit status">
        <p className={styles.sectionLabel}>
          Status
        </p>
        {PRACTITIONER_STATUSES.map((word) => {
          const selected = (choice ?? (visit.state === word ? word : null)) === word;
          return (
            <label key={word} className={`${styles.option} ${selected ? styles.optionOn : ''}`}>
              <input type="radio" name="visit-status" checked={selected} onChange={() => setChoice(word)} data-el={`PRAC-VISIT-STATUS-${word.toUpperCase()}`} />
              <span className={`${styles.radio} ${selected ? styles.radioOn : ''}`} aria-hidden="true" />
              {STATUS_LABEL[word]}
            </label>
          );
        })}
      </div>

      {choice === 'on-my-way' && sharing ? (
        <div className={styles.estimate} role="group" aria-label="Estimated arrival">
          <p className={styles.sectionLabel}>About how long?</p>
          <div className={styles.chips}>
            {ETA_CHOICES.map((minutes) => (
              <Chip key={minutes} pressed={eta === minutes} onPressedChange={(on) => setEta(on ? minutes : null)} dataEl={`PRAC-VISIT-ETA-${minutes}`}>
                {`${minutes} min`}
              </Chip>
            ))}
          </div>
          <p className={styles.note}>You choose the estimate. Your phone’s position is not sent.</p>
        </div>
      ) : null}

      {saved === null ? null : (
        <p className={styles.saved} role="status">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
          <span>{`Status updated: ${STATUS_LABEL[saved]}.`}</span>
        </p>
      )}
      {failed ? <Banner tone="warning" title="We could not send that. Try again." /> : null}
    </PhoneScreen>
  );
}

export function VisitLoader({ id }: { id: string }) {
  const router = useRouter();
  const [reload, setReload] = useState(0);
  const read = useBffRead(`/api/bff/practitioner/visits/${encodeURIComponent(id)}`, parseVisit, reload);

  useEffect(() => {
    if (read.kind === 'ended') router.replace(PIN);
  }, [read, router]);

  if (read.kind === 'failed') return <PhoneFailed title="Visit" backHref={SHIFT}>We could not load this visit. Try again shortly.</PhoneFailed>;
  if (read.kind !== 'ready') return <PhoneOpening title="Visit" backHref={SHIFT} label="Opening the visit." />;
  const visit = read.value;
  const changed = () => setReload((n) => n + 1);

  if (visit.state === 'offered') return <OfferView visit={visit} onChanged={changed} />;
  if (ACTIVE_STATES.includes(visit.state)) return <ActiveView visit={visit} onChanged={changed} />;
  return <Closed state={visit.state} />;
}
