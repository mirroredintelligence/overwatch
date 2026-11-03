'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Button } from '@/components/ui/Button';
import { SUMMARY_LABELS, type SummaryView, summaryText } from '@/lib/advisor/summary';
import styles from './finish.module.css';

// The read-only summary for SystmOne (W15). "Copy summary" writes plain text, one row per line. If
// the clipboard refuses, the text is shown and selected, and the user is told to press Ctrl+C.
// On a wide screen it is a card with the copy button in its heading row. On a phone the rows fold
// into a disclosure that starts closed, and the copy button stays in view under it.

const COPIED = 'Copied to clipboard';
const PRESS_CTRL_C = 'Press Ctrl+C to copy';
// The same breakpoint as the two cards in finish.module.css.
const WIDE = '(min-width: 56rem)';

function subscribeWide(onChange: () => void) {
  if (typeof window.matchMedia !== 'function') return () => undefined;
  const media = window.matchMedia(WIDE);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function isWide() {
  return typeof window.matchMedia === 'function' && window.matchMedia(WIDE).matches;
}

function useWideScreen(): boolean {
  return useSyncExternalStore(subscribeWide, isWide, () => false);
}

export function SummaryCopy({ summary }: { summary: SummaryView }) {
  const [status, setStatus] = useState<string | null>(null);
  const [fallback, setFallback] = useState(false);
  const plain = useRef<HTMLPreElement>(null);
  const wide = useWideScreen();
  const text = summaryText(summary);

  // Selects the fallback text once it is on the screen, so the user can copy it at once.
  useEffect(() => {
    if (!fallback || plain.current === null) return;
    const range = document.createRange();
    range.selectNodeContents(plain.current);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [fallback, wide]);

  function copy() {
    // The write starts inside the click, as the browser requires for the clipboard.
    navigator.clipboard.writeText(text).then(
      () => setStatus(COPIED),
      () => {
        setFallback(true);
        setStatus(PRESS_CTRL_C);
      },
    );
  }

  const rows = (
    <dl className={styles.rows}>
      {SUMMARY_LABELS.map((row) => (
        <div key={row.key} className={styles.row}>
          <dt className={styles.term}>{row.label}</dt>
          <dd className={styles.value}>{summary[row.key]}</dd>
        </div>
      ))}
    </dl>
  );
  const copyButton = (
    <Button variant="secondary" dataEl="ADV-FIN-COPY-BTN" onClick={copy}>
      Copy summary
    </Button>
  );
  const plainText = fallback ? (
    <pre ref={plain} className={styles.plain}>
      {text}
    </pre>
  ) : null;
  const statusLine = (
    <p role="status" className={styles.status}>
      {status}
    </p>
  );

  if (wide) {
    return (
      <section id="summary" className={styles.summary} aria-labelledby="summary-heading">
        <div className={styles.head}>
          <div>
            <h2 id="summary-heading" className={styles.heading}>
              Summary for SystmOne
            </h2>
            <p className={styles.note}>Read only. Paste it into the referral.</p>
          </div>
          {copyButton}
        </div>
        {rows}
        {plainText}
        {statusLine}
      </section>
    );
  }

  return (
    <section id="summary" className={styles.summary} aria-labelledby="summary-heading">
      <details className={styles.fold}>
        <summary className={styles.foldHead}>
          <h2 id="summary-heading" className={styles.heading}>
            Summary for SystmOne
          </h2>
          <span className={styles.chevron} aria-hidden="true">
            ▾
          </span>
        </summary>
        <p className={styles.note}>Read only. Paste it into the referral.</p>
        {rows}
      </details>
      {plainText}
      {copyButton}
      {statusLine}
    </section>
  );
}
