import { tenantStore } from '@/lib/storage/tenantStore';

// Which lessons this browser has finished (W53). It is kept through the one browser-storage helper
// (lib/storage/tenantStore, TEN-050): per host, interface state only, wiped on sign-out, and nothing
// when the browser blocks storage (the lessons still run and simply remember nothing). The interface
// (getDone, markDone, subscribeProgress, doneSnapshot) is the one a back-end progress store would
// replace later, so no page reads storage directly.

const NAME = 'learn.done';
const listeners = new Set<() => void>();

const isIds = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string');

export function getDone(): Set<string> {
  return new Set(tenantStore.get(NAME, isIds) ?? []);
}

export function markDone(id: string): void {
  const done = getDone();
  done.add(id);
  // Blocked storage: the lesson is still finished for this page, and nothing is kept.
  tenantStore.set(NAME, [...done]);
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
