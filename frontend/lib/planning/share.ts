// The share of a whole, as a whole percentage (W51). A suppressed count (under 10) has no share,
// and no whole means no share is invented.

export function share(count: number | null, whole: number): number | null {
  if (count === null || !(whole > 0)) return null;
  return Math.round((count / whole) * 100);
}
