'use client';

import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import { MAX_FIGURE, type Said } from '@/lib/lead/phonedBody';
import styles from './LeadPhonedDialog.module.css';
import formStyles from '@/components/advisor/dialog-body.module.css';

// The shift lead's "Enter what they told me by phone" (W17, W42, W43; DEC-920). A service's answer with no case:
// what it said on the phone and how many it can take. The lead's answer is recorded as advisor-phoned, through
// the BFF's phoned route. "Not accepting" carries no figure. A form that is refused stays open, and says so.
// It is a side sheet over the counters column: the counters stay visible, and focus stays in the sheet until it
// closes, then goes back to whatever opened it (the card's button).

const ANSWERS: readonly { said: Said; label: string; id: string }[] = [
  { said: 'accepting', label: 'Accepting', id: 'ACCEPTING' },
  { said: 'limited', label: 'Limited', id: 'LIMITED' },
  { said: 'not-accepting', label: 'Not accepting', id: 'NOT-ACCEPTING' },
];

const ERROR = 'Enter how many they can take, as a whole number';
const SAVE_FAILED = 'The position could not be saved. Try again.';
const WHOLE = /^\d+$/;
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type LeadPhonedDialogProps = {
  open: boolean;
  serviceId: string;
  serviceName: string;
  onClose: () => void;
  /** Called once the back end has recorded the answer, before the dialog closes. */
  onRecorded?: () => void;
};

export function LeadPhonedDialog({ open, serviceId, serviceName, onClose, onRecorded }: LeadPhonedDialogProps) {
  if (!open) return null;
  return <OpenLeadPhonedDialog serviceId={serviceId} serviceName={serviceName} onClose={onClose} onRecorded={onRecorded} />;
}

// The side sheet's shell: a named modal dialog that takes focus on open, traps Tab inside, closes on Escape,
// and returns focus to the element that had it when it opened.
function Sheet({
  title,
  sub,
  dataEl,
  onClose,
  children,
}: {
  title: string;
  sub: string;
  dataEl: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const sheet = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // The opener is whatever had focus when the sheet appeared; it gets focus back when the sheet unmounts.
    const opener = document.activeElement as HTMLElement | null;
    const first = sheet.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? sheet.current)?.focus();
    return () => {
      opener?.focus?.();
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || sheet.current === null) return;
    const items = Array.from(sheet.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      ref={sheet}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      className={styles.sheet}
      data-el={dataEl}
      onKeyDown={onKeyDown}
    >
      <h2 id={titleId} className={styles.title}>
        {title}
      </h2>
      <p className={styles.sub}>{sub}</p>
      {children}
    </div>
  );
}

// The form's state lives in its own component, so opening the sheet starts it empty.
function OpenLeadPhonedDialog({ serviceId, serviceName, onClose, onRecorded }: Omit<LeadPhonedDialogProps, 'open'>) {
  const [said, setSaid] = useState<Said | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const keyRef = useRef<string | null>(null);
  const valueId = useId();

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (said === null || busy) return;
    let value: number | undefined;
    if (said !== 'not-accepting') {
      const figure = Number(text);
      if (!WHOLE.test(text) || figure > MAX_FIGURE) {
        setError(true);
        return;
      }
      value = figure;
    }
    setError(false);
    setFailed(false);
    setBusy(true);
    keyRef.current ??= newIdempotencyKey();
    const body = value === undefined ? { said } : { said, value };
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/phoned`, body, keyRef.current);
    setBusy(false);
    if (!result.ok) {
      setFailed(true);
      return;
    }
    keyRef.current = null;
    onRecorded?.();
    onClose();
  }

  return (
    <Sheet title="Enter what they told me by phone" sub={serviceName} dataEl="LEAD-PHONED-DIALOG" onClose={onClose}>
      <form className={styles.form} onSubmit={(event) => void save(event)} noValidate>
        <fieldset className={formStyles.group}>
          <legend className={formStyles.legend}>{`What did ${serviceName} tell you?`}</legend>
          {ANSWERS.map((answer) => (
            <OptionButton
              key={answer.said}
              selected={said === answer.said}
              onSelect={() => setSaid(answer.said)}
              dataEl={`LEAD-PHONED-${answer.id}`}
            >
              {answer.label}
            </OptionButton>
          ))}
        </fieldset>

        {said === null || said === 'not-accepting' ? null : (
          <div className={formStyles.field}>
            <label className={formStyles.label} htmlFor={valueId}>
              How many can they take?
            </label>
            <input
              id={valueId}
              className={formStyles.input}
              type="text"
              inputMode="numeric"
              autoComplete="off"
              value={text}
              onChange={(event) => setText(event.target.value)}
              aria-invalid={error ? 'true' : undefined}
              aria-describedby={error ? `${valueId}-error` : undefined}
            />
            {error ? (
              <p id={`${valueId}-error`} className={formStyles.error}>
                {ERROR}
              </p>
            ) : null}
          </div>
        )}

        <p className={formStyles.note}>
          The board will show this as told by phone, with your name and the time. The service is asked to report by text
          as usual at the next due time.
        </p>
        {failed ? (
          <p role="alert" className={formStyles.error}>
            {SAVE_FAILED}
          </p>
        ) : null}

        <div className={formStyles.actions}>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" busy={busy} disabled={said === null} dataEl="LEAD-PHONED-SAVE-BTN">
            Save position
          </Button>
        </div>
      </form>
    </Sheet>
  );
}
