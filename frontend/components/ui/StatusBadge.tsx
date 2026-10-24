// DEC-010 red stub: names and signatures only; the body returns nothing.
export type StatusCode =
  | 'accepting'
  | 'limited'
  | 'not-accepting'
  | 'over-capacity'
  | 'not-updated'
  | 'out-of-hours'
  | 'last-known';

export const STATUS_LABELS = {} as Record<StatusCode, string>;

export function StatusBadge(_props: { status: StatusCode; size?: 'sm' | 'lg' }): null {
  return null;
}
