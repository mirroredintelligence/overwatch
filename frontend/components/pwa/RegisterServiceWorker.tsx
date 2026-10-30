'use client';

import { useEffect } from 'react';

// Registers the service worker in production builds only (W32). Nothing here asks for
// notification permission: that happens only after the consent screen (W34).
export function RegisterServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // A failed registration leaves the app working online; nothing personal is logged.
    });
  }, []);
  return null;
}
