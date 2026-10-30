// Times on the registration status pages, in London time, as the screens write them (W27).

const DAY_MONTH_TIME = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/London',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});
const HOUR_MINUTE = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

function parts(formatter: Intl.DateTimeFormat, iso: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const part of formatter.formatToParts(new Date(iso))) found[part.type] = part.value;
  return found;
}

/** "23 Oct 14:30": the day, the short month and the London time. */
export function londonDayMonthTime(iso: string): string {
  const p = parts(DAY_MONTH_TIME, iso);
  return `${p.day} ${p.month} ${p.hour}:${p.minute}`;
}

/** "16:00": the London hour and minute. */
export function londonHourMinute(iso: string): string {
  const p = parts(HOUR_MINUTE, iso);
  return `${p.hour}:${p.minute}`;
}
