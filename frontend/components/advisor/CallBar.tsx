'use client';

import { useEffect, useState } from 'react';
import styles from './CallBar.module.css';

// The call bar (W10): "Call in progress · 02:14 · Ambulance crew". The timer counts from openedAt
// and updates each second. It is not a live region: a figure read out every second is noise.

const SECOND_MS = 1000;

/** mm:ss for a span of milliseconds (minutes may pass 59 and keep counting). */
export function elapsedText(milliseconds: number): string {
  const total = Math.max(0, Math.floor(milliseconds / SECOND_MS));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function CallBar({ openedAt, referrer }: { openedAt: string; referrer: string }) {
  const start = Date.parse(openedAt);
  // The clock is read on each tick, never during render, so the server and the first browser render
  // agree (no hydration mismatch). Until the first tick, a second after mount, the timer reads 00:00.
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), SECOND_MS);
    return () => clearInterval(timer);
  }, []);

  const elapsed = now === null || Number.isNaN(start) ? 0 : now - start;
  return (
    <div className={styles.bar} data-el="ADV-CALLBAR">
      {`Call in progress · ${elapsedText(elapsed)} · ${referrer}`}
    </div>
  );
}
