'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { SUMMARY_LABELS, type SummaryView, summaryText } from '@/lib/advisor/summary';
import styles from './finish.module.css';

// The read-only summary for SystmOne (W15). "Copy summary" writes plain text, one row per line. If
// the clipboard refuses, the text is shown and selected, and the user is told to press Ctrl+C.

const COPIED = 'Copied to clipboard';
const PRESS_CTRL_C = 'Press Ctrl+C to copy';

export function SummaryCopy({ summary }: { summary: SummaryView }) {
  const [status, setStatus] = useState<string | null>(null);
  const [fallback, setFallback] = useState(false);
  const plain = useRef<HTMLPreElement>(null);
  const text = summaryText(summary);

  // Selects the fallback text once it is on the screen, so the user can copy it at once.
  useEffect(() => {
    if (!fallback || plain.current === null) return;
    const range = document.createRange();
    range.selectNodeContents(plain.current);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [fallback]);

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

  return (
    <section id="summary" className={styles.summary} aria-labelledby="summary-heading">
      <h2 id="summary-heading" className={styles.heading}>
        Summary for SystmOne
      </h2>
      <p className={styles.note}>Read-only. Paste into the referral.</p>
      <dl className={styles.rows}>
        {SUMMARY_LABELS.map((row) => (
          <div key={row.key} className={styles.row}>
            <dt className={styles.term}>{row.label}</dt>
            <dd className={styles.value}>{summary[row.key]}</dd>
          </div>
        ))}
      </dl>
      {fallback ? <pre ref={plain} className={styles.plain}>{text}</pre> : null}
      <p role="status" className={styles.status}>
        {status}
      </p>
      <div className={styles.actions}>
        <Button variant="primary" dataEl="ADV-FIN-COPY-BTN" onClick={copy}>
          Copy summary
        </Button>
        <Button variant="neutral" href="#outcome">
          Done
        </Button>
      </div>
    </section>
  );
}
