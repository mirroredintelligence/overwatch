'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useId, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import styles from './Clinical.module.css';

// On duty (W44, ClinicalAdvisor screen 2): available, busy or away. It starts where the clinician left it
// (the back end's read of their own presence, DEC-780). Away says what happens to unfinished requests
// before it is saved. A count that could not be read is not shown as zero.

type Presence = 'available' | 'busy' | 'away';
const CHOICES: readonly { value: Presence; label: string; words: string }[] = [
  { value: 'available', label: 'Available', words: 'Advisors can send you requests now.' },
  { value: 'busy', label: 'Busy', words: 'You finish what you are doing first. Requests wait in the queue.' },
  { value: 'away', label: 'Away', words: 'You will not get alerts.' },
];

const DOT_CLASS: Record<Presence, string> = {
  available: styles.dotAvailable ?? '',
  busy: styles.dotBusy ?? '',
  away: styles.dotAway ?? '',
};

export function DutyForm({ available, waiting, presence: initial }: { available: number | null; waiting: number | null; presence: Presence | null }) {
  const router = useRouter();
  const ids = useId();
  const [presence, setPresence] = useState<Presence | null>(initial);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (presence === null) return;
    setBusy(true);
    setError(null);
    const result = await bffRequest<{ presence: string }>('/api/bff/clinical/presence', { method: 'PUT', body: { presence } });
    setBusy(false);
    if (!result.ok) {
      setSaved(false);
      setError('Could not save your status. Try again.');
      return;
    }
    setSaved(true);
    router.refresh();
  };

  return (
    <div className={styles.duty}>
      <section className={`${styles.card} ${styles.dutyMain}`} aria-labelledby={`${ids}-heading`}>
        <h1 id={`${ids}-heading`} className={styles.heading}>Are you taking requests?</h1>
        <div className={styles.choices} role="group" aria-label="Your status">
          {CHOICES.map((choice) => (
            <button
              key={choice.value}
              type="button"
              aria-label={choice.label}
              aria-pressed={presence === choice.value}
              aria-describedby={`${ids}-${choice.value}`}
              className={styles.choice}
              data-el={`CLIN-DUTY-${choice.value.toUpperCase()}`}
              onClick={() => {
                setPresence(choice.value);
                setSaved(false);
              }}
            >
              <span className={`${styles.dot} ${DOT_CLASS[choice.value]}`} aria-hidden="true" />
              <span className={styles.choiceText}>
                <span>{choice.label}</span>
                <span id={`${ids}-${choice.value}`} className={styles.choiceWords}>{choice.words}</span>
              </span>
            </button>
          ))}
        </div>
        {presence === 'away' ? (
          <Banner tone="warning" title="Your unfinished requests go back to the queue." />
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" busy={busy} disabled={presence === null} onClick={save} dataEl="CLIN-DUTY-SAVE-BTN">
            Save status
          </Button>
          <p className={styles.note}>Advisors see how many of you are available. They see your name only after you take a request.</p>
        </div>
        {saved ? <p role="status">Status saved.</p> : null}
        {error ? <p role="alert" className={styles.error}>{error}</p> : null}
        {initial === null && presence === null ? <p>You have not set your status.</p> : null}
      </section>
      <section className={`${styles.card} ${styles.side}`} aria-label="Right now">
        <p className={styles.eyebrow}>Right now</p>
        {waiting === null || available === null ? (
          <p>The counts could not be read.</p>
        ) : (
          <>
            <div className={styles.figure}>
              <span className={styles.figureNumber}>{waiting}</span>
              <span>{`request${waiting === 1 ? '' : 's'} waiting`}</span>
            </div>
            <div className={styles.figure}>
              <span className={styles.figureNumber}>{available}</span>
              <span>{`clinical advisor${available === 1 ? '' : 's'} available now`}</span>
            </div>
          </>
        )}
        <Link href="/clinical/requests" className={styles.sideLink}>Open the queue</Link>
      </section>
    </div>
  );
}
