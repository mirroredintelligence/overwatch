'use client';

import { useEffect, useState } from 'react';
import { browserLaunchEnv, takeLaunchSplash } from '@/lib/pwa/launch';
import { Splash } from './Splash';

// The brand splash at the launch of the installed app, once per session. It is shown when the page runs as
// an installed app (display-mode: standalone, or iOS's navigator.standalone), and only the first time in a
// browser session: later navigations, reloads and tabs of the same session do not show it again
// (lib/pwa/launch.ts holds the once-per-session flag). A browser tab never shows it. Sign-out clears the
// flag, so the next person to launch the app sees it once.
//
// It never blocks the page: the page is rendered and usable underneath, the overlay lets every tap and key
// through (pointer-events: none) and is hidden from assistive technology, and when the splash cannot be
// shown (no storage, no matchMedia) nothing is shown. Reduced motion is the splash's own: it shows the
// finished logo for a short moment (components/brand/Splash.tsx).

export function LaunchSplash() {
  const [showing, setShowing] = useState(false);

  useEffect(() => {
    // Decided after the first paint and not in the effect's body, so the page is never held for it.
    const decide = setTimeout(() => setShowing(takeLaunchSplash(browserLaunchEnv())), 0);
    return () => clearTimeout(decide);
  }, []);

  if (!showing) return null;
  return (
    <div aria-hidden="true" data-css={JSON.stringify({ pointerEvents: 'none' })} data-el="LAUNCH-SPLASH">
      <Splash onComplete={() => setShowing(false)} />
    </div>
  );
}
