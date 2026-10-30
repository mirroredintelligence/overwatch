'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { londonTime } from '@/lib/board/format';
import { bffRequest } from '@/lib/bff/browser';
import { RELEASE } from '@/lib/release';
import { currentSessionId } from '@/lib/telemetry/events';
import { roleLabel, type AppMode, type DeviceType } from '@/lib/support/share';
import exec from '@/components/exec/Exec.module.css';
import styles from './SupportCode.module.css';

// "Your support code" (W56, SafetyConcern screen 5). The page reads whether a code is live for this session
// and until when (W7A, DEC-772): the back end keeps only a keyed hash of the code, so it can say that sharing
// is on but can never give the code back. The code is made on request, shown here once and held only in this
// page's memory: not in browser storage, not in telemetry, not in the console. After a reload the page says a
// code is live and until when, and that the code is shown only once. Support sees the pages used, the buttons
// pressed and any errors; never what was typed.

export const POLL_MS = 15_000;
const BASE = '/api/bff/support/code';
const ACCESSES = '/api/bff/support/accesses';

type Access = { openedAt: string; role: string };

function deviceType(): DeviceType {
  const width = typeof window === 'undefined' ? 1024 : window.innerWidth;
  if (width <= 600) return 'phone';
  if (width <= 1024) return 'tablet';
  return 'desktop';
}

function appMode(): AppMode {
  return typeof window !== 'undefined' && window.matchMedia?.('(display-mode: standalone)').matches ? 'installed' : 'browser';
}

export function SupportCode() {
  // The code is held in memory only, from the moment it is made until the page goes.
  const [code, setCode] = useState<{ code: string; expiresAt: string } | null>(null);
  // Whether a code is live, as the back end says: undefined while reading, null when it could not be read.
  const [live, setLive] = useState<{ active: boolean; expiresAt?: string } | null | undefined>(undefined);
  const [accesses, setAccesses] = useState<Access[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState<'copied' | 'by-hand' | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [busy, setBusy] = useState(false);
  const codeRef = useRef<HTMLParagraphElement>(null);
  const sessionId = useRef<string | null>(null);

  const readState = useCallback(async () => {
    sessionId.current ??= currentSessionId();
    const result = await bffRequest<{ active: boolean; expiresAt?: string }>(`${BASE}?sessionId=${encodeURIComponent(sessionId.current)}`);
    setLive(result.ok ? result.data : null);
  }, []);

  const makeCode = useCallback(async () => {
    setFailed(false);
    setStopped(false);
    sessionId.current = currentSessionId();
    const result = await bffRequest<{ code: string; expiresAt: string }>(BASE, {
      method: 'POST',
      body: { sessionId: sessionId.current, deviceType: deviceType(), appMode: appMode(), release: RELEASE },
    });
    if (!result.ok) {
      // A second code is refused while one is live: read the state again so the page says so.
      if (result.status === 409) void readState();
      else setFailed(true);
      return;
    }
    setCode(result.data);
    setLive({ active: true, expiresAt: result.data.expiresAt });
  }, [readState]);

  const readAccesses = useCallback(async () => {
    if (sessionId.current === null) return;
    const result = await bffRequest<Access[]>(`${ACCESSES}?sessionId=${encodeURIComponent(sessionId.current)}`);
    if (result.ok) setAccesses(result.data);
  }, []);

  useEffect(() => {
    // Whether sharing is on is read when the page opens; no code is made by opening the page.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void readState();
  }, [readState]);

  const active = live?.active === true;
  useEffect(() => {
    // Who has opened the session is read while sharing is on, and every 15 seconds.
    if (!active) return undefined;
    void readAccesses();
    const timer = setInterval(() => void readAccesses(), POLL_MS);
    return () => clearInterval(timer);
  }, [active, readAccesses]);

  const copy = async () => {
    if (code === null) return;
    try {
      await navigator.clipboard.writeText(code.code);
      setCopied('copied');
    } catch {
      const range = document.createRange();
      if (codeRef.current) range.selectNodeContents(codeRef.current);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
      setCopied('by-hand');
    }
  };

  const stop = async () => {
    if (sessionId.current === null) return;
    setBusy(true);
    const result = await bffRequest(`${BASE}?sessionId=${encodeURIComponent(sessionId.current)}`, { method: 'DELETE' });
    setBusy(false);
    setConfirming(false);
    if (!result.ok) {
      setFailed(true);
      return;
    }
    setCode(null);
    setLive({ active: false });
    setAccesses(null);
    setStopped(true);
  };

  return (
    <div className={exec.stack}>
      <h1 className={exec.heading}>Your support code</h1>

      {failed ? <p role="alert" className={exec.error}>We could not make a code. Try again.</p> : null}
      {live === null ? (
        <div role="alert" className={exec.error}>
          <p>We could not tell whether a code is live. Try again.</p>
          <Button variant="secondary" onClick={() => void readState()} dataEl="HELP-SHARE-CHECK-BTN">Check again</Button>
        </div>
      ) : null}
      {code !== null ? (
        <section className={styles.codeBox} aria-label="Your code">
          <p ref={codeRef} className={styles.code} data-el="HELP-SHARE-CODE">{code.code}</p>
          <p>{`Valid until ${londonTime(code.expiresAt)}`}</p>
        </section>
      ) : null}
      {code === null && live?.active === true && live.expiresAt !== undefined ? (
        <section className={styles.codeBox} aria-label="Sharing is on">
          <p>{`A code is live until ${londonTime(live.expiresAt)}.`}</p>
          <p>The code is shown only once, when it is made. If you no longer have it, stop sharing and make a new one.</p>
        </section>
      ) : null}
      {live?.active === false && !stopped ? <p>Support cannot see your session.</p> : null}
      {stopped ? <p role="status">Sharing stopped.</p> : null}

      <p>Support can see the pages you used, the buttons you pressed and any errors. They cannot see what you typed or any patient information.</p>

      <section className={exec.section} aria-labelledby="share-opened">
        <h2 id="share-opened" className={exec.cardTitle}>Who has opened your session</h2>
        {accesses === null || accesses.length === 0 ? (
          <p>Nobody has opened it yet.</p>
        ) : (
          <ul>
            {accesses.map((access) => (
              <li key={access.openedAt}>{`${londonTime(access.openedAt)} by ${roleLabel(access.role)}`}</li>
            ))}
          </ul>
        )}
      </section>

      <div className={exec.actions}>
        {live?.active === false ? (
          <Button variant="primary" onClick={() => void makeCode()} dataEl="HELP-SHARE-MAKE-BTN">Make a support code</Button>
        ) : null}
        {code !== null ? <Button variant="secondary" onClick={copy} dataEl="HELP-SHARE-COPY-BTN">Copy code</Button> : null}
        {live?.active === true ? (
          <Button variant="secondary" onClick={() => setConfirming(true)} dataEl="HELP-SHARE-STOP-BTN">Stop sharing now</Button>
        ) : null}
      </div>
      {copied === 'copied' ? <p role="status">Copied.</p> : null}
      {copied === 'by-hand' ? <p role="status">Press Ctrl+C to copy</p> : null}

      {confirming ? (
        <div role="group" aria-label="Stop sharing?" className={styles.confirm}>
          <p>Stop sharing? Support will lose access at once.</p>
          <div className={exec.actions}>
            <Button variant="primary" busy={busy} onClick={stop} dataEl="HELP-SHARE-STOP-CONFIRM">Stop sharing</Button>
            <Button variant="neutral" onClick={() => setConfirming(false)} dataEl="HELP-SHARE-STOP-CANCEL">Cancel</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
