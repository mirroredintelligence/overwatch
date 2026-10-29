'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { NumberStepper } from '@/components/ui/NumberStepper';
import { sendAnswer, type AnswerOutcome } from '@/lib/links/browser';
import { londonHm, type LinkAnswer, type LinkView, splitUnitLabel, thanksQuery } from '@/lib/links/model';
import { LinkExpired } from './LinkExpired';
import styles from './Reporter.module.css';

// The reporter's answer to a capacity link: confirm the figure on record, or send a new one,
// or say the service is closed. Opening the page changes nothing; only a press posts.

const MIN_FIGURE = 0;
const MAX_FIGURE = 999;

const OUT_OF_RANGE = (min: number, max: number) =>
  `That is outside your usual range of ${min} to ${max}. Check it and press Send new number again to confirm.`;

const MESSAGES: Partial<Record<AnswerOutcome['kind'], string>> = {
  'send-number': 'Please send the number.',
  'rate-limited': 'Too many tries. Wait a few minutes, then try again.',
  failed: 'We could not record that. Try again.',
};

type Props = { token: string; view: LinkView };

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function CapacityResponder({ token, view }: Props) {
  const router = useRouter();
  const { noun, window: windowText } = splitUnitLabel(view.unitLabel);
  const [value, setValue] = useState<number | null>(view.recordedValue);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<number | null>(null);
  const [expired, setExpired] = useState(false);

  if (expired) return <LinkExpired token={token} />;

  const recorded = view.recordedValue !== null;
  const asOf = view.asOf === null ? null : londonHm(view.asOf);
  const until = londonHm(view.replyBy);
  const nextDue = view.nextDue === null ? null : londonHm(view.nextDue);

  async function send(answer: LinkAnswer) {
    setBusy(true);
    setNotice(null);
    const outcome = await sendAnswer(token, view.csrfToken, answer);
    switch (outcome.kind) {
      case 'recorded':
        // Keep busy while the thank-you page opens, so nothing posts twice.
        router.push(`/l/${token}/thanks?${thanksQuery(outcome.answered).toString()}`);
        return;
      case 'out-of-range':
        setBusy(false);
        setFlagged(value);
        setNotice(OUT_OF_RANGE(outcome.usualMin, outcome.usualMax));
        return;
      case 'gone':
        setBusy(false);
        setExpired(true);
        return;
      default:
        setBusy(false);
        setNotice(MESSAGES[outcome.kind] ?? MESSAGES.failed ?? null);
    }
  }

  function changeFigure(next: number | null) {
    setValue(next);
    // A figure changed after an out-of-range warning must be checked again before it is sent.
    if (next !== flagged) setFlagged(null);
  }

  const sendFigure = () => {
    if (value === null) return;
    void send(flagged === value ? { action: 'number', value, confirmOutOfRange: true } : { action: 'number', value });
  };

  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>DIUCS capacity update</p>
      <h1 className={styles.title}>{view.serviceName}</h1>

      {recorded ? (
        <>
          <p className={styles.question}>
            {`We have ${view.recordedValue} ${view.unitLabel}${asOf === null ? '' : `, as of ${asOf}`}. Still right?`}
          </p>
          <Button variant="primary" busy={busy} dataEl="REP-LINK-CONFIRM-BTN" onClick={() => send({ action: 'confirm' })}>
            {`Yes, still ${view.recordedValue}`}
          </Button>
          <p className={styles.or}>Or send a new number</p>
        </>
      ) : (
        <p className={styles.question}>{`How many ${noun} can you take${windowText ? ` ${windowText}` : ''}?`}</p>
      )}

      <NumberStepper
        label={capitalise(view.unitLabel)}
        value={value}
        min={MIN_FIGURE}
        max={MAX_FIGURE}
        onChange={changeFigure}
        hint={`${noun} · usual range ${view.usualMin} to ${view.usualMax}`}
        dataEl="REP-LINK-STEPPER"
      />

      <Button
        variant="primary"
        busy={busy}
        disabled={value === null}
        dataEl="REP-LINK-SEND-BTN"
        onClick={sendFigure}
      >
        {value === null ? 'Choose a number to send' : 'Send new number'}
      </Button>
      <Button variant="neutral" busy={busy} dataEl="REP-LINK-CLOSED-BTN" onClick={() => send({ action: 'closed' })}>
        We are closed to referrals
      </Button>

      {notice !== null ? (
        <Banner tone="warning" title={notice} dataEl="REP-LINK-NOTICE" />
      ) : null}

      <p className={styles.footer}>
        {recorded ? 'No login. ' : ''}
        {`This link works once and expires at ${until}.`}
        {nextDue !== null ? ` Next update due ${nextDue}.` : ''}
      </p>
    </main>
  );
}
