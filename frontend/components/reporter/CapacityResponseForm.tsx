'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { NumberStepper } from '@/components/ui/NumberStepper';
import { splitUnitLabel } from '@/lib/links/model';
import styles from './Reporter.module.css';

// The reporter's answer to one service's capacity prompt (W35). The same questions as the link
// page: confirm the figure on record, send a new one, or say the service is closed. Nothing is sent
// until a button is pressed; the parent does the sending and says what to show.

export type Prompt = {
  service: string;
  unitLabel: string;
  recordedValue: number | null;
  asOf: string | null;
  low: number;
  high: number;
  replyBy: string | null;
  nextDue: string | null;
};

export type Answer = { kind: 'confirm' } | { kind: 'number'; value: number } | { kind: 'closed' };

type Props = {
  prompt: Prompt;
  busy: boolean;
  notice: string | null;
  /** False after the back end refused a second confirm: only a number can be sent then. */
  confirmAllowed: boolean;
  onAnswer: (answer: Answer) => void;
  /** Set when the phone holds several services and one is being changed (W38). */
  serviceBanner?: { name: string; position: number; total: number };
};

const MIN = 0;
const MAX = 999;

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function CapacityResponseForm({ prompt, busy, notice, confirmAllowed, onAnswer, serviceBanner }: Props) {
  const { noun, window: windowText } = splitUnitLabel(prompt.unitLabel);
  const [value, setValue] = useState<number | null>(null);
  const recorded = prompt.recordedValue;


  return (
    <main className={styles.page}>
      {serviceBanner !== undefined ? (
        <section className={styles.banner} aria-label="Service being updated">
          <h2 className={styles.bannerTitle}>{`Updating ${serviceBanner.name}`}</h2>
          <p>{`${serviceBanner.name} · ${serviceBanner.position} of ${serviceBanner.total}`}</p>
          <a href="/app/update">Back to both</a>
        </section>
      ) : null}
      <p className={styles.eyebrow}>Capacity update</p>
      <h1 className={styles.title}>{prompt.service}</h1>

      {recorded !== null ? (
        <>
          <p className={styles.question}>
            {`We have ${recorded} ${prompt.unitLabel}${prompt.asOf === null ? '' : `, as of ${prompt.asOf}`}. Still right?`}
          </p>
          {confirmAllowed ? (
            <Button variant="primary" busy={busy} dataEl="REP-APP-CONFIRM-BTN" onClick={() => onAnswer({ kind: 'confirm' })}>
              {`Yes, still ${recorded}`}
            </Button>
          ) : null}
          <p className={styles.or}>Or send a new number</p>
        </>
      ) : (
        <p className={styles.question}>{`How many ${noun} can you take${windowText ? ` ${windowText}` : ''}?`}</p>
      )}

      <NumberStepper
        label={capitalise(noun)}
        value={value}
        min={MIN}
        max={MAX}
        onChange={setValue}
        hint={`${noun} · usual range ${prompt.low} to ${prompt.high}`}
        dataEl="REP-APP-STEPPER"
      />

      <Button
        variant="primary"
        busy={busy}
        disabled={value === null}
        dataEl="REP-APP-SEND-BTN"
        onClick={() => value !== null && onAnswer({ kind: 'number', value })}
      >
        {value === null ? 'Choose a number to send' : 'Send new number'}
      </Button>
      <Button variant="neutral" busy={busy} dataEl="REP-APP-CLOSED-BTN" onClick={() => onAnswer({ kind: 'closed' })}>
        We are closed to referrals
      </Button>

      {notice !== null ? <Banner tone="warning" title={notice} dataEl="REP-APP-NOTICE" /> : null}
    </main>
  );
}
