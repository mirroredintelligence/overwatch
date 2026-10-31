'use client';

import { useEffect, useState } from 'react';
import styles from './Splash.module.css';

const HOLD_MS = 2400;
const FADE_MS = 300;

/**
 * Brand splash: ring draws, scan line sweeps, core ignites, one glint, wordmark reveals.
 * Calls onComplete after the fade. Reduced motion shows the finished logo for a short moment.
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
        <svg className={styles.mark} viewBox="0 0 120 120" aria-hidden="true" focusable="false">
          <defs>
            <clipPath id="splash-ring-clip">
              <circle cx="60" cy="60" r="45" />
            </clipPath>
            <linearGradient id="splash-glint" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#FFFFFF" stopOpacity="0" />
              <stop offset="0.5" stopColor="#FFFFFF" stopOpacity="0.9" />
              <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
            </linearGradient>
          </defs>

          <circle className={styles.bloom} cx="60" cy="60" r="34" />

          <circle className={styles.ring} cx="60" cy="60" r="50" pathLength="1" />

          <g clipPath="url(#splash-ring-clip)">
            <g className={styles.scan}>
              <rect x="0" y="58.5" width="120" height="3" />
            </g>
            <g className={styles.glint}>
              <rect x="-20" y="-20" width="40" height="160" transform="rotate(35 60 60)" fill="url(#splash-glint)" />
            </g>
          </g>

          <circle className={styles.core} cx="60" cy="60" r="20" />
        </svg>

        <span className={styles.word}>Overwatch</span>
      </div>
      <span className={styles.srOnly}>Overwatch</span>
    </div>
  );
}
