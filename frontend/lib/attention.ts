// The attention treatment of the advisor-side board and the service cards (DEC-1365). One rule, in one place:
// what a card is, in words, decides whether it glows. The glow is added to the status shape and word, never
// instead of them, and it never changes the order of the cards (the back end orders; nothing here ranks).
//
// Precedence: a figure that cannot be relied on (stale) is shown as stale even when its last status was over
// capacity or limited, because that status is no longer known to be true. Over capacity is next. Limited and
// not accepting get a calm static ring. Everything else (accepting, out of hours) has none.

export type Attention = 'stale' | 'over' | 'limited' | 'closed';

export type AttentionInput = {
  status: string;
  /** The figure is not current: last known, paused, not updated, unavailable or older than the stale limit. */
  stale: boolean;
};

export function attentionOf({ status, stale }: AttentionInput): Attention | null {
  if (stale || status === 'not-updated' || status === 'last-known') return 'stale';
  if (status === 'over-capacity') return 'over';
  if (status === 'limited') return 'limited';
  if (status === 'not-accepting') return 'closed';
  return null;
}

/** The global classes of app/attention.css for a card, or an empty string. */
export function attentionClass(attention: Attention | null): string {
  return attention === null ? '' : `attention attention-${attention}`;
}
