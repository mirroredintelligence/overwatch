import type { Assessment } from '@/lib/board/liveness';

export type LastKnown = Extract<Assessment, { mode: 'last-known' }>;

export function LastKnownBanner({ lastKnown }: { lastKnown: LastKnown }) {
  void lastKnown;
  return null;
}
