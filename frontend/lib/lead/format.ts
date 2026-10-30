// Words and clock times for the shift lead's pages. Every clock time is London time (DEC-151),
// whatever the server's or the browser's zone is, and a duration is said in hours and minutes.

const LONDON = 'Europe/London';
const MINUTE_MS = 60_000;

const clock = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

const day = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** "12:00", in London time. */
export function clockTime(iso: string): string {
  return clock.format(new Date(iso));
}

/** "Fri 30 Oct, 14:12", in London time, for the page header. */
export function dateTimeLine(now: number): string {
  return day.format(new Date(now));
}

/** "2 hrs 12 min", "50 min", "1 hr", "2 hrs". */
export function overdueText(minutes: number): string {
  const whole = Math.max(0, Math.floor(minutes));
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  if (hours === 0) return `${rest} min`;
  const hoursWord = hours === 1 ? '1 hr' : `${hours} hrs`;
  return rest === 0 ? hoursWord : `${hoursWord} ${rest} min`;
}

/** "2 hrs 10 min ago", against the given now (epoch ms). */
export function agoText(iso: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(iso)) / MINUTE_MS);
  return `${overdueText(minutes)} ago`;
}

export function servicesWord(count: number): string {
  return count === 1 ? 'service' : 'services';
}
