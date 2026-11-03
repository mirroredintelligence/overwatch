'use client';

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Banner, Button } from '@/components/ui';
import { StatusTag } from '@/components/ui/StatusTag';
import { londonTime } from '@/lib/board/format';
import { connectScreen, previewScreen, ScreenClientError, type ScreenField, type ScreenPreview } from '@/lib/screens/client';
import { parseCode, parseLocation, parseName } from '@/lib/screens/model';
import styles from './ScreenForm.module.css';

export type ConnectApi = {
  connect: (input: { code: string; name: string; location: string | null }) => Promise<{ name: string; status: 'online'; connectedAt: string }>;
  /** The confirm step's look at the code (TEN-072): the organisation, when the screen first asked, its kind. */
  preview: (code: string) => Promise<ScreenPreview>;
};

const SCREEN_API: ConnectApi = { connect: connectScreen, preview: previewScreen };
const LEAD_HOME = '/lead';
const SCREENS_LIST = '/lead/screens';
const SIGN_IN_AGAIN = '/sign-in?next=%2Flead%2Fscreens%2Fnew';
const THROTTLED = 'Too many attempts. Wait a few minutes and try again.';
const UNAVAILABLE = 'We could not connect the screen. Try again.';
const FIELD_ORDER: readonly ScreenField[] = ['code', 'name', 'location'];
const ORGANISATION_FALLBACK = 'Your organisation';

type Values = Record<ScreenField, string>;
type Errors = Partial<Record<ScreenField, string>>;
type Notice = 'throttled' | 'unavailable' | 'unauthorised' | null;
type Connected = { name: string; connectedAt: string };
type Checking = { input: { code: string; name: string; location: string | null }; preview: ScreenPreview };
type Step = 'form' | 'refused' | 'check' | 'connected';

const DEVICE_CLASS_WORDS: Record<ScreenPreview['deviceClass'], string> = { 'wall-display': 'Wall display' };

const EMPTY: Values = { code: '', name: '', location: '' };

// The lead types the code a wall display shows, and names the screen. The stage shows one step at a time:
// the form, a refused code (the words in an alert, the code kept), "Is this the right screen?", then
// connected. Every value stays in state across the steps. The page offers no choice of board and sends
// no tenant: a screen shows the organisation's own board.
export function ScreenForm({ api = SCREEN_API }: { api?: ConnectApi }) {
  const ids = { code: useId(), name: useId(), location: useId() };
  const [values, setValues] = useState<Values>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<Connected | null>(null);
  // The check step (ScreenClaim): what the lead typed, and what the back end says about the code.
  const [checking, setChecking] = useState<Checking | null>(null);
  // The back end did not know the code: the refused step shows the words and keeps the code.
  const [refused, setRefused] = useState(false);
  // Focus goes where the person needs it next: the first wrong field, the code after a refusal, or the
  // heading of the next step. A new object each time, so the same field is focused again after a second
  // wrong answer.
  const [focus, setFocus] = useState<{ id: string } | null>(null);
  const sending = useRef(false);
  const titleId = `${ids.code}-title`;
  const checkId = `${ids.code}-check`;
  const doneId = `${ids.code}-done`;
  const hintId = `${ids.code}-hint`;
  const refusedId = `${ids.code}-refused`;
  const step: Step = connected !== null ? 'connected' : checking !== null ? 'check' : refused ? 'refused' : 'form';
  useEffect(() => {
    if (focus !== null) document.getElementById(focus.id)?.focus();
  }, [focus]);
  const focusOn = (field: ScreenField | 'confirmation' | 'check') =>
    setFocus({ id: field === 'confirmation' ? doneId : field === 'check' ? checkId : ids[field] });

  function change(field: ScreenField, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => (current[field] === undefined ? current : { ...current, [field]: undefined }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const code = parseCode(values.code);
    const name = parseName(values.name);
    const location = parseLocation(values.location);
    const found: Errors = {};
    if (!code.ok) found.code = code.error;
    if (!name.ok) found.name = name.error;
    if (!location.ok) found.location = location.error;
    setNotice(null);
    if (!code.ok || !name.ok || !location.ok) {
      setRefused(false);
      setErrors(found);
      const first = FIELD_ORDER.find((field) => found[field] !== undefined);
      if (first !== undefined) focusOn(first);
      return;
    }
    setErrors({});
    setRefused(false);
    sending.current = true;
    setBusy(true);
    const input = { code: code.value, name: name.value, location: location.value };
    try {
      // The lead is shown what the screen is before it is connected (ScreenClaim, TEN-072).
      const preview = await api.preview(input.code);
      setChecking({ input, preview });
      focusOn('check');
    } catch (error) {
      failWith(error);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  async function connect() {
    if (sending.current || checking === null) return;
    sending.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.connect(checking.input);
      setConnected({ name: result.name, connectedAt: result.connectedAt });
      setChecking(null);
      focusOn('confirmation');
    } catch (error) {
      // A refused code or a field the back end disliked sends the lead back to the form to fix it.
      const kind = error instanceof ScreenClientError ? error.kind : 'unavailable';
      if (kind === 'not-found' || kind === 'invalid') setChecking(null);
      failWith(error);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  function failWith(error: unknown) {
    const kind = error instanceof ScreenClientError ? error.kind : 'unavailable';
    if (kind === 'not-found') {
      setErrors({});
      setRefused(true);
      focusOn('code');
    } else if (kind === 'invalid') {
      const field = error instanceof ScreenClientError && error.field !== undefined ? error.field : 'name';
      setErrors({ [field]: error instanceof ScreenClientError && error.detail !== undefined ? error.detail : 'Check what you typed.' });
      focusOn(field);
    } else {
      setNotice(kind === 'throttled' ? 'throttled' : kind === 'unauthorised' ? 'unauthorised' : 'unavailable');
    }
  }

  function another() {
    setValues(EMPTY);
    setErrors({});
    setNotice(null);
    setConnected(null);
    setChecking(null);
    setRefused(false);
    focusOn('code');
  }

  function cancelCheck() {
    // Back to the form with what was typed; nothing was connected.
    setChecking(null);
    setNotice(null);
    focusOn('code');
  }

  function backToForm() {
    setRefused(false);
    focusOn('code');
  }

  const typedCode = values.code.trim();
  const live = step === 'connected';

  const notices = (
    <>
      {notice === 'throttled' ? <Banner tone="warning" title={THROTTLED} dataEl="LEAD-SCREEN-MESSAGE" /> : null}
      {notice === 'unavailable' ? <Banner tone="warning" title={UNAVAILABLE} dataEl="LEAD-SCREEN-MESSAGE" /> : null}
      {notice === 'unauthorised' ? (
        <Banner tone="warning" title="Your session has ended. Sign in again." dataEl="LEAD-SCREEN-MESSAGE">
          <a href={SIGN_IN_AGAIN}>Sign in</a>
        </Banner>
      ) : null}
    </>
  );

  // The text fields. The code also announces its format; a message or the refusal is linked to the field.
  const text = (field: ScreenField, alertId?: string) => {
    const bad = alertId !== undefined || errors[field] !== undefined;
    const describedBy = [field === 'code' ? hintId : null, alertId ?? null, errors[field] === undefined ? null : `${ids[field]}-error`]
      .filter((part): part is string => part !== null)
      .join(' ');
    return {
      id: ids[field],
      value: values[field],
      onChange: (event: { target: { value: string } }) => change(field, event.target.value),
      className: `${styles.input} ${bad ? styles.invalid : ''}`,
      'aria-invalid': bad ? (true as const) : undefined,
      'aria-describedby': describedBy === '' ? undefined : describedBy,
      autoComplete: 'off',
      spellCheck: false,
    };
  };
  const error = (field: ScreenField) =>
    errors[field] === undefined ? null : (
      <p id={`${ids[field]}-error`} className={styles.error}>
        {errors[field]}
      </p>
    );

  // The screen the lead is pairing, beside the stage. It shows the code as it is typed, and the live board once connected.
  const screenCard = (
    <section className={styles.screen} aria-label="The wall screen">
      <p className={styles.kicker}>The wall screen</p>
      <div className={styles.tv}>
        <div className={styles.tvCode} data-live={live ? 'true' : undefined} aria-hidden="true">
          <p className={styles.tvCaption}>Pair this screen</p>
          <p className={styles.tvNumber}>{typedCode === '' ? 'Enter the code' : typedCode}</p>
        </div>
        <div className={styles.tvBoard} data-live={live ? 'true' : undefined} aria-hidden="true">
          {[0, 1, 2, 3, 4, 5].map((tile) => (
            <span key={tile} className={styles.tvTile} />
          ))}
        </div>
      </div>
      <p className={styles.note}>
        {live ? 'Showing the board for your organisation.' : 'This is what is on the wall now. The screen asks for a new code every few minutes.'}
      </p>
    </section>
  );

  // One step at a time: the stage is keyed by the step, so each one comes in with a short fade.
  const frame = (content: ReactNode) => (
    <main className={styles.page}>
      <div className={styles.layout}>
        {screenCard}
        <div className={styles.stage} key={step}>
          {content}
        </div>
      </div>
    </main>
  );

  if (step === 'connected' && connected !== null) {
    return frame(
      <section className={styles.card} aria-labelledby={doneId}>
        <div className={styles.check} aria-hidden="true">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </div>
        <h1 id={doneId} className={styles.heading} tabIndex={-1}>
          {`${connected.name} is connected`}
        </h1>
        <p className={styles.lead}>It is showing your organisation’s board now. You can change which board it shows, or unpair it, from the list of screens.</p>
        <p>
          <StatusTag variant="live">{`Online, updated ${londonTime(connected.connectedAt)}`}</StatusTag>
        </p>
        <div className={styles.actions}>
          <Button variant="primary" href={SCREENS_LIST} dataEl="LEAD-SCREEN-LIST-BTN">
            See all screens
          </Button>
          <Button variant="neutral" onClick={another} dataEl="LEAD-SCREEN-ADD-ANOTHER-BTN">
            Add another
          </Button>
        </div>
      </section>,
    );
  }

  if (step === 'check' && checking !== null) {
    return frame(
      <section className={styles.card} aria-labelledby={checkId}>
        <h1 id={checkId} className={styles.heading} tabIndex={-1}>
          Is this the right screen?
        </h1>
        {notices}
        <dl className={styles.tiles}>
          <div className={styles.tile}>
            <dt className={styles.tileKey}>For</dt>
            <dd className={styles.tileValue}>{checking.preview.organisationName ?? ORGANISATION_FALLBACK}</dd>
          </div>
          <div className={styles.tile}>
            <dt className={styles.tileKey}>Asked for a code</dt>
            <dd className={styles.tileValue}>{londonTime(checking.preview.firstSeenAt)}</dd>
          </div>
          <div className={styles.tile}>
            <dt className={styles.tileKey}>It is a</dt>
            <dd className={styles.tileValue}>{DEVICE_CLASS_WORDS[checking.preview.deviceClass]}</dd>
          </div>
        </dl>
        <p className={styles.lead}>If you did not just start this screen, do not connect it. Anyone with the code could ask for the board.</p>
        <div className={styles.actions}>
          <Button variant="primary" busy={busy} onClick={() => void connect()} dataEl="SCREENS-CLAIM-CONFIRM-BTN">
            Yes, connect it
          </Button>
          <Button variant="neutral" onClick={cancelCheck} dataEl="SCREENS-CLAIM-CANCEL-BTN">
            No, go back
          </Button>
        </div>
      </section>,
    );
  }

  if (step === 'refused') {
    return frame(
      <section className={styles.card} aria-labelledby={titleId}>
        <h1 id={titleId} className={styles.heading}>
          Type the code the screen shows
        </h1>
        <form className={styles.form} onSubmit={submit} noValidate>
          <div id={refusedId} role="alert" className={styles.refused}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5M12 16h.01" />
            </svg>
            <p>
              <b>That code is not valid or has expired.</b> Check the screen for a new code.
            </p>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={ids.code}>
              Code
            </label>
            <p id={hintId} className={styles.hint}>
              6 numbers
            </p>
            <input {...text('code', refusedId)} inputMode="numeric" data-el="LEAD-SCREEN-CODE-FIELD" />
            {error('code')}
          </div>
          <div className={styles.actions}>
            <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-SCREEN-CONNECT-BTN">
              Check the code again
            </Button>
            <Button variant="neutral" onClick={backToForm} dataEl="LEAD-SCREEN-BACK-BTN">
              Back
            </Button>
          </div>
        </form>
      </section>,
    );
  }

  return frame(
    <section className={styles.card} aria-labelledby={titleId}>
      <p className={styles.kicker}>Add a wall screen</p>
      <h1 id={titleId} className={styles.heading}>
        Type the code the screen shows
      </h1>
      {notices}
      <form className={styles.form} onSubmit={submit} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={ids.code}>
            Code
          </label>
          <p id={hintId} className={styles.hint}>
            6 numbers
          </p>
          <input {...text('code')} inputMode="numeric" data-el="LEAD-SCREEN-CODE-FIELD" />
          {error('code')}
        </div>
        <div className={styles.fieldRow}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={ids.name}>
              Name this screen
            </label>
            <input {...text('name')} data-el="LEAD-SCREEN-NAME-FIELD" />
            {error('name')}
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={ids.location}>
              Where is it? <span className={styles.optional}>(optional)</span>
            </label>
            <input {...text('location')} data-el="LEAD-SCREEN-LOCATION-FIELD" />
            {error('location')}
          </div>
        </div>
        <p className={styles.note}>A screen shows capacity only, never patient information.</p>
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-SCREEN-CONNECT-BTN">
            Check the code
          </Button>
          <Button variant="neutral" href={LEAD_HOME} dataEl="LEAD-SCREEN-CANCEL-BTN">
            Cancel
          </Button>
        </div>
        <p className={styles.note}>
          <a href={SCREENS_LIST}>See the screens already connected</a>
        </p>
      </form>
    </section>,
  );
}
