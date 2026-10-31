'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Banner, Button } from '@/components/ui';
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
const NOT_FOUND = 'That code is not valid or has expired. Check the screen for a new code.';
const THROTTLED = 'Too many attempts. Wait a few minutes and try again.';
const UNAVAILABLE = 'We could not connect the screen. Try again.';
const FIELD_ORDER: readonly ScreenField[] = ['code', 'name', 'location'];

type Values = Record<ScreenField, string>;
type Errors = Partial<Record<ScreenField, string>>;
type Notice = 'throttled' | 'unavailable' | 'unauthorised' | null;
type Connected = { name: string; connectedAt: string };
type Checking = { input: { code: string; name: string; location: string | null }; preview: ScreenPreview };

const DEVICE_CLASS_WORDS: Record<ScreenPreview['deviceClass'], string> = { 'wall-display': 'Wall display' };

const EMPTY: Values = { code: '', name: '', location: '' };

// The lead types the code a wall display shows, and names the screen. Every message sits beside the
// field it is about and is linked to it; what the page checks, the BFF checks again. The page offers
// no choice of board and sends no tenant: a screen shows the organisation's own board.
export function ScreenForm({ api = SCREEN_API }: { api?: ConnectApi }) {
  const ids = { code: useId(), name: useId(), location: useId() };
  const [values, setValues] = useState<Values>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<Connected | null>(null);
  // The confirm step (ScreenClaim): what the lead typed, and what the back end says about the code.
  const [checking, setChecking] = useState<Checking | null>(null);
  // Focus goes where the person needs it next: the first wrong field, or the confirmation. A new
  // object each time, so the same field is focused again after a second wrong answer.
  const [focus, setFocus] = useState<{ id: string } | null>(null);
  const sending = useRef(false);
  const doneId = `${ids.code}-done`;
  const checkId = `${ids.code}-check`;
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
      setErrors(found);
      const first = FIELD_ORDER.find((field) => found[field] !== undefined);
      if (first !== undefined) focusOn(first);
      return;
    }
    setErrors({});
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
      setErrors({ code: NOT_FOUND });
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
    focusOn('code');
  }

  function cancelCheck() {
    // Back to the form with what was typed; nothing was connected.
    setChecking(null);
    setNotice(null);
    focusOn('code');
  }

  if (connected !== null) {
    return (
      <main className={styles.page}>
        <div className={styles.panel}>
          <section className={styles.card} aria-labelledby={doneId}>
            <h1 id={doneId} className={styles.heading} tabIndex={-1}>
              Screen connected
            </h1>
            <p>{connected.name} is now showing the live board.</p>
            <dl className={styles.rows}>
              <div className={styles.row}>
                <dt>Status</dt>
                <dd>{`Online, updated ${londonTime(connected.connectedAt)}`}</dd>
              </div>
              <div className={styles.row}>
                <dt>Shows</dt>
                <dd>Capacity only. No patient information.</dd>
              </div>
              <div className={styles.row}>
                <dt>If it goes offline</dt>
                <dd>The board shows Last known and says so</dd>
              </div>
            </dl>
            <div className={styles.actions}>
              <Button variant="secondary" onClick={another} dataEl="LEAD-SCREEN-ADD-ANOTHER-BTN">
                Add another screen
              </Button>
              <Button variant="secondary" href={SCREENS_LIST} dataEl="LEAD-SCREEN-LIST-BTN">
                See all screens
              </Button>
              <Button variant="primary" href={LEAD_HOME} dataEl="LEAD-SCREEN-DONE-BTN">
                Done
              </Button>
            </div>
          </section>
        </div>
      </main>
    );
  }

  if (checking !== null) {
    const seen = londonTime(checking.preview.firstSeenAt);
    return (
      <main className={styles.page}>
        <div className={styles.panel}>
          <section className={styles.card} aria-labelledby={checkId}>
            <h1 id={checkId} className={styles.heading} tabIndex={-1}>
              Check before you connect
            </h1>
            {notice === 'throttled' ? <Banner tone="warning" title={THROTTLED} dataEl="LEAD-SCREEN-MESSAGE" /> : null}
            {notice === 'unavailable' ? <Banner tone="warning" title={UNAVAILABLE} dataEl="LEAD-SCREEN-MESSAGE" /> : null}
            {notice === 'unauthorised' ? (
              <Banner tone="warning" title="Your session has ended. Sign in again." dataEl="LEAD-SCREEN-MESSAGE">
                <a href={SIGN_IN_AGAIN}>Sign in</a>
              </Banner>
            ) : null}
            <p>
              {`You are connecting a screen to ${checking.preview.organisationName ?? 'your organisation'}. It will show our organisation’s capacity only. It never shows patient information.`}
            </p>
            <p className={styles.note}>{`First seen ${seen} · ${DEVICE_CLASS_WORDS[checking.preview.deviceClass]}`}</p>
            <div className={styles.actions}>
              <Button variant="primary" busy={busy} onClick={() => void connect()} dataEl="SCREENS-CLAIM-CONFIRM-BTN">
                Connect screen
              </Button>
              <Button variant="neutral" onClick={cancelCheck} dataEl="SCREENS-CLAIM-CANCEL-BTN">
                Cancel
              </Button>
            </div>
          </section>
        </div>
      </main>
    );
  }

  const text = (field: ScreenField) => ({
    id: ids[field],
    value: values[field],
    onChange: (event: { target: { value: string } }) => change(field, event.target.value),
    className: `${styles.input} ${errors[field] === undefined ? '' : styles.invalid}`,
    'aria-invalid': errors[field] === undefined ? undefined : (true as const),
    'aria-describedby': errors[field] === undefined ? undefined : `${ids[field]}-error`,
    autoComplete: 'off',
    spellCheck: false,
  });
  const error = (field: ScreenField) =>
    errors[field] === undefined ? null : (
      <p id={`${ids[field]}-error`} className={styles.error}>
        {errors[field]}
      </p>
    );

  return (
    <main className={styles.page}>
      <div className={styles.panel}>
        <section className={styles.card} aria-labelledby={`${ids.code}-title`}>
          <h1 id={`${ids.code}-title`} className={styles.heading}>
            Add a wall screen
          </h1>
          {notice === 'throttled' ? <Banner tone="warning" title={THROTTLED} dataEl="LEAD-SCREEN-MESSAGE" /> : null}
          {notice === 'unavailable' ? <Banner tone="warning" title={UNAVAILABLE} dataEl="LEAD-SCREEN-MESSAGE" /> : null}
          {notice === 'unauthorised' ? (
            <Banner tone="warning" title="Your session has ended. Sign in again." dataEl="LEAD-SCREEN-MESSAGE">
              <a href={SIGN_IN_AGAIN}>Sign in</a>
            </Banner>
          ) : null}
          <form className={styles.form} onSubmit={submit} noValidate>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={ids.code}>
                Code shown on the screen
                <span className={styles.hint} data-el="LEAD-SCREEN-CODE-HINT">
                  Required
                </span>
              </label>
              <input {...text('code')} inputMode="numeric" data-el="LEAD-SCREEN-CODE-FIELD" />
              {error('code')}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={ids.name}>
                Screen name
                <span className={styles.hint} data-el="LEAD-SCREEN-NAME-HINT">
                  Required
                </span>
              </label>
              <input {...text('name')} data-el="LEAD-SCREEN-NAME-FIELD" />
              {error('name')}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={ids.location}>
                Where it is
                <span className={styles.hint} data-el="LEAD-SCREEN-LOCATION-HINT">
                  Optional
                </span>
              </label>
              <input {...text('location')} data-el="LEAD-SCREEN-LOCATION-FIELD" />
              {error('location')}
            </div>
            <p className={styles.note}>This screen will show capacity only. It never shows patient information.</p>
            <p className={styles.note}>
              <a href={SCREENS_LIST}>See the screens already connected</a>
            </p>
            <div className={styles.actions}>
              <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-SCREEN-CONNECT-BTN">
                Connect screen
              </Button>
              <Button variant="neutral" href={LEAD_HOME} dataEl="LEAD-SCREEN-CANCEL-BTN">
                Cancel
              </Button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
