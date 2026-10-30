// The end of a calendar day in London, as an instant with its own offset (DEC-654). A cover "until a date"
// ends at 23:59:59 London time on that date, in GMT or BST as the day is.

const FORMAT = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/London',
  hourCycle: 'h23',
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: 'numeric',
  minute: 'numeric',
  second: 'numeric',
});

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** London's offset from UTC at an instant, in minutes. */
function londonOffsetMinutes(ms: number): number {
  const parts: Record<string, string> = {};
  for (const part of FORMAT.formatToParts(new Date(ms))) parts[part.type] = part.value;
  const wall = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  );
  return Math.round((wall - ms) / 60_000);
}

/** 23:59:59 on the given London date, as ISO 8601 with the offset in force then. Throws for a non-date. */
export function endOfLondonDay(date: string): string {
  const match = DATE.exec(date);
  if (match === null) throw new Error('not a date');
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const naive = Date.UTC(year, month - 1, day, 23, 59, 59);
  const check = new Date(naive);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    throw new Error('not a calendar date');
  }
  // The offset at the instant is found twice: the first guess can sit on the other side of a change.
  let offset = londonOffsetMinutes(naive);
  offset = londonOffsetMinutes(naive - offset * 60_000);
  const sign = offset < 0 ? '-' : '+';
  const abs = Math.abs(offset);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return `${date}T23:59:59${sign}${hh}:${mm}`;
}
