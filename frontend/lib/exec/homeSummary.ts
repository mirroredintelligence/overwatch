import { durationText, londonTime } from '@/lib/board/format';
import type { Board, BoardEntry } from '@/lib/board/types';

// The exec home's figures (W40): what needs attention, the pressure word, and one line per service.
// Pure: a board and a clock in, text out. The pressure itself is the back end's (`board.pressure`);
// this module only names it.

const ATTENTION: ReadonlySet<BoardEntry['status']> = new Set(['over-capacity', 'not-accepting', 'not-updated']);
const LIMITED_OR_WORSE: ReadonlySet<BoardEntry['status']> = new Set(['limited', 'not-accepting', 'over-capacity']);

/** The services that need the executive's attention now: over capacity, not accepting, or not updated. */
export function needsAttention(board: Board): BoardEntry[] {
  return board.entries.filter((entry) => ATTENTION.has(entry.status));
}

/** Services limited or worse, against the services in hours (domain-rules 1.7: out-of-hours is left out). */
export function limitedOrWorse(board: Board): { limited: number; inHours: number } {
  const inHours = board.entries.filter((entry) => entry.status !== 'out-of-hours');
  return { limited: inHours.filter((entry) => LIMITED_OR_WORSE.has(entry.status)).length, inHours: inHours.length };
}

const PRESSURE_WORDS: Readonly<Record<string, string>> = { normal: 'Normal', watch: 'Watch', high: 'High' };

/** The pressure as a word, so the state is never carried by colour alone. An unknown value says so. */
export function pressureChip(pressure: string): { word: string; label: string } {
  const word = PRESSURE_WORDS[pressure] ?? 'Unknown';
  return { word, label: `System pressure ${word.toLowerCase()}` };
}

function minutesBetween(from: string, to: string): number {
  return Math.max(0, Math.floor((Date.parse(to) - Date.parse(from)) / 60_000));
}

/** One line for a service that needs attention: what it is, and when it was last reported. */
export function attentionLine(entry: BoardEntry, now: string): string {
  const reported = entry.reportedAt;
  if (entry.status === 'not-updated') {
    return reported === null ? 'Not updated, no report yet' : `Not updated for ${durationText(minutesBetween(reported, now))}`;
  }
  const at = reported === null ? '' : `, reported ${londonTime(reported)}`;
  if (entry.status === 'over-capacity') {
    const over = entry.overBy !== null && entry.overBy > 0 ? ` +${entry.overBy}` : '';
    return `Over capacity${over}${at}`;
  }
  return `Not accepting${at}`;
}
