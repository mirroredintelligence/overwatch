'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { OptionButton } from '@/components/ui/OptionButton';
import { ACTIVE_STATES, parseAnswer, parseVisit, PRACTITIONER_STATUSES, type PractitionerStatus, type Visit, type VisitState } from '@/lib/practitioner/answers';
import { countdown, secondsLeft, useBffRead } from '@/lib/practitioner/browser';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import { PhoneScreen, wantedText } from './PhoneScreen';
import styles from './practitioner.module.css';

// The visit offer and the accepted visit (RadarPhone 2 and 3), one resource at two stages. An offer shows
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

function Mark({ solid }: { solid?: boolean }) {
  return (
    <svg viewBox="0 0 30 30" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <circle cx="15" cy="15" r="12" />
      {solid === true ? <path d="M9.5 15.5l4 4 7-8" /> : <path d="M10.5 8.5h9M10.5 21.5h9M11.5 8.5c0 4 7 4 7 6.5s-7 2.5-7 6.5" />}
    </svg>
  );
}

const CLOSED_TEXT: Partial<Record<VisitState, { title: string; text: string }>> = {
  done: { title: 'Visit done', text: 'Thank you. The details of this visit have been removed from the app.' },
  'not-reached': { title: 'Could not reach the patient', text: 'The coordination team has been told. The details of this visit have been removed from the app.' },
  declined: { title: 'Offer declined', text: 'You declined this offer. Your colleagues’ offers are not affected.' },
  expired: { title: 'Offer expired', text: 'The time to answer this offer has passed.' },
  withdrawn: { title: 'No longer open', text: 'This visit was taken by a colleague, or the booking was cancelled.' },
};

function Closed({ state }: { state: VisitState }) {
  const text = CLOSED_TEXT[state] ?? { title: 'No longer open', text: 'This visit is no longer open.' };
  return (
    <PhoneScreen title="Visit" backHref={SHIFT} actions={<Button variant="primary" href={SHIFT} dataEl="PRAC-CLOSED-SHIFT-BTN">Back to my shift</Button>}>
      <h1 className={styles.title}>{text.title}</h1>
      <p>{text.text}</p>
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
      <span className={styles.badge}>
        <Mark />
        New offer
      </span>
      <h1 className={styles.title}>{visit.need}</h1>
      <div className={styles.panel} data-el="PRAC-OFFER-FACTS">
        <p>
          Area <strong>{visit.sector}</strong> (sector)
        </p>
        <p>
          <strong>{wantedText(visit.wantedWithin)}</strong>
        </p>
        {visit.fitsMinutes === null ? null : (
          <p>
            Fits your round: <strong>{`+${visit.fitsMinutes} min`}</strong> to your next visit
          </p>
        )}
        <p>
          Offer expires in <span className={styles.countdown}>{countdown(left)}</span>
        </p>
      </div>
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
        <>
          {visit.address === undefined ? (
            <Button variant="secondary" disabled dataEl="PRAC-VISIT-MAPS-BTN">
              Open in maps
            </Button>
          ) : (
            <Button variant="secondary" href={mapsLink(visit.address)} dataEl="PRAC-VISIT-MAPS-BTN">
              Open in maps
            </Button>
          )}
          <Button variant="primary" busy={busy} disabled={choice === null} dataEl="PRAC-VISIT-UPDATE-BTN" onClick={() => void update()}>
            Update status
          </Button>
        </>
      }
    >
      <span className={`${styles.badge} ${styles.badgeSolid}`}>
        <Mark solid />
        Accepted
      </span>
      <h1 className={styles.title}>{`Visit ${visit.reference}`}</h1>
      <div className={styles.panel} data-el="PRAC-VISIT-DETAILS">
        <p>Address and contact now shown to you only.</p>
        {visit.address === undefined || visit.contact === undefined ? (
          <p>They could not be shown here. Phone the coordination team.</p>
        ) : (
          <>
            <p className={styles.panelTitle}>{visit.address}</p>
            <p>{visit.contact}</p>
          </>
        )}
        <p>{`${wantedText(visit.wantedWithin)}.`}</p>
        {visit.etaAt === null ? null : <p>{`Estimated arrival shared: ${clock(visit.etaAt)}.`}</p>}
      </div>

      <div className={styles.group} role="group" aria-label="Visit status">
        {PRACTITIONER_STATUSES.map((word) => (
          <OptionButton key={word} selected={(choice ?? (visit.state === word ? word : null)) === word} onSelect={() => setChoice(word)} dataEl={`PRAC-VISIT-STATUS-${word.toUpperCase()}`}>
            {STATUS_LABEL[word]}
          </OptionButton>
        ))}
      </div>

      {choice === 'on-my-way' && sharing ? (
        <div className={styles.group} role="group" aria-label="Estimated arrival">
          <div className={styles.labelRow}>
            <p className={styles.label}>About how long?</p>
            <span className={styles.optional}>Optional</span>
          </div>
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

      {saved === null ? null : <p role="status">{`Status updated: ${STATUS_LABEL[saved]}.`}</p>}
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

  if (read.kind === 'failed') return <PhoneScreen title="Visit" backHref={SHIFT}><p>We could not load this visit. Try again shortly.</p></PhoneScreen>;
  if (read.kind !== 'ready') return <PhoneScreen title="Visit" backHref={SHIFT}><p role="status">Opening the visit</p></PhoneScreen>;
  const visit = read.value;
  const changed = () => setReload((n) => n + 1);

  if (visit.state === 'offered') return <OfferView visit={visit} onChanged={changed} />;
  if (ACTIVE_STATES.includes(visit.state)) return <ActiveView visit={visit} onChanged={changed} />;
  return <Closed state={visit.state} />;
}
