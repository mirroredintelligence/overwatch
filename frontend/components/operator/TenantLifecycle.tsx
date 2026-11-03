// The last step of the Go live page and the life of an organisation (TEN-083) now live under ./funnel. This file only
// re-exports them, so the imports of the page keep working.

export type { Notice } from './funnel/shared';
export { GoLiveStep } from './funnel/GoLiveStep';
export { LifecyclePanel } from './funnel/LifecyclePanel';
