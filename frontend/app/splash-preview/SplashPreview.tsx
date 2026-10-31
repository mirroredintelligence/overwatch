'use client';

import { useCallback, useState } from 'react';
import { Splash } from '../../components/brand/Splash';

export function SplashPreview() {
  const [run, setRun] = useState(1);
  const [showing, setShowing] = useState(true);

  const done = useCallback(() => setShowing(false), []);

  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', gap: 16, padding: 24 }}>
      {showing && <Splash key={run} onComplete={done} />}
      {!showing && (
        <button
          type="button"
          onClick={() => {
            setRun((r) => r + 1);
            setShowing(true);
          }}
          style={{ minHeight: 52, padding: '0 24px', borderRadius: 14, fontSize: 18 }}
        >
          Replay splash
        </button>
      )}
    </main>
  );
}
