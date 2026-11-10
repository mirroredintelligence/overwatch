import { useSyncExternalStore } from 'react';

// True on a phone-width screen (the overview then shows tabs and a short paged list). False where the browser cannot
// say, and on the server, so the wide page is the one that is always whole.

export const NARROW_QUERY = '(max-width: 640px)';

function subscribe(onChange: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => undefined;
  const query = window.matchMedia(NARROW_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

function snapshot(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(NARROW_QUERY).matches;
}

export function useNarrow(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
