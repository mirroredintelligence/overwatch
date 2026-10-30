// Whole minutes until a time, for "Returns to the queue in 9 min" (W44). Never negative.

export function minutesLeft(returnsAt: string, now: string): number {
  const end = Date.parse(returnsAt);
  const at = Date.parse(now);
  if (Number.isNaN(end)) throw new Error('returnsAt is not a time');
  if (Number.isNaN(at)) throw new Error('now is not a time');
  return Math.max(0, Math.floor((end - at) / 60_000));
}
