// Which lessons this browser has finished (W53). It is kept in localStorage, inside try/catch: a
// browser that blocks storage still runs the lessons, and simply remembers nothing. The interface
// (getDone, markDone, subscribeProgress, doneSnapshot) is the one a back-end progress store would
// replace later, so no page reads localStorage directly.

const KEY = 'diucs-learn-done';
const listeners = new Set<() => void>();

export function getDone(): Set<string> {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []);
  } catch {
    return new Set();
  }
}

export function markDone(id: string): void {
  const done = getDone();
  done.add(id);
  try {
    window.localStorage.setItem(KEY, JSON.stringify([...done]));
  } catch {
    // Blocked storage: the lesson is still finished for this page, and nothing is kept.
  }
  for (const listener of listeners) listener();
}

/** Calls the listener when a lesson is marked done. Returns the way to stop listening. */
export function subscribeProgress(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** A string that changes exactly when the set of finished lessons does, for useSyncExternalStore. */
export function doneSnapshot(): string {
  return [...getDone()].sort().join(',');
}
