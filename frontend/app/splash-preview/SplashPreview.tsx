'use client';

import { useCallback, useState } from 'react';
import { Splash } from '../../components/brand/Splash';
import styles from './SplashPreview.module.css';

export function SplashPreview() {
  const [run, setRun] = useState(1);
  const [showing, setShowing] = useState(true);

  const done = useCallback(() => setShowing(false), []);

  return (
    <main className={styles.page}>
      {showing && <Splash key={run} onComplete={done} />}
      {!showing && (
        <button
          type="button"
          className={styles.replay}
          onClick={() => {
            setRun((r) => r + 1);
            setShowing(true);
          }}
        >
          Replay splash
        </button>
      )}
    </main>
  );
}
