'use client';

import { useEffect, useState } from 'react';
import styles from './Splash.module.css';

const HOLD_MS = 2400;
const FADE_MS = 300;

/**
 * Brand splash: one ring and a dot settle with a single spring, then the name. Calls onComplete after the fade.
 * Reduced motion shows the finished mark for a short moment (the CSS module holds it still).
 */
export function Splash({ onComplete }: { onComplete?: () => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const hold = reduced ? 300 : HOLD_MS;
    const fade = reduced ? 150 : FADE_MS;
    const toLeave = window.setTimeout(() => setLeaving(true), hold);
    const toDone = window.setTimeout(() => onComplete?.(), hold + fade);
    return () => {
      window.clearTimeout(toLeave);
      window.clearTimeout(toDone);
    };
  }, [onComplete]);

  return (
    <div className={`${styles.splash} ${leaving ? styles.leaving : ''}`} role="presentation">
      <div className={styles.lockup}>
        <svg className={styles.mark} viewBox="0 0 26 26" aria-hidden="true" focusable="false">
          <circle cx="13" cy="13" r="10" className={styles.ring} />
          <path d="M3 13h20" className={styles.ring} />
          <circle cx="13" cy="13" r="4.2" className={styles.dot} />
        </svg>
        <span className={styles.word}>Overwatch</span>
      </div>
    </div>
  );
}
