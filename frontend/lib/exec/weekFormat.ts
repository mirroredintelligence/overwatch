// The week summary's words for a figure (W41). A withheld figure (the back end's small-group rule, a count
// under ten) is never shown as a number or a percentage: it reads "fewer than 10".

export type Count = { value: number | null; suppressed?: boolean };

export const WITHHELD = 'fewer than 10';
export const NO_FIGURE = 'No figure yet';

/** A whole count, grouped as en-GB does (640, 1,648). */
export function formatCount(figure: Count): string {
  if (figure.suppressed === true) return WITHHELD;
  if (figure.value === null) return NO_FIGURE;
  return figure.value.toLocaleString('en-GB');
}

/** A percentage, rounded to a whole number. Never a percentage for a withheld value. */
export function formatPct(figure: Count): string {
  if (figure.suppressed === true) return WITHHELD;
  if (figure.value === null) return NO_FIGURE;
  return `${Math.round(figure.value)}%`;
}

/** Whole minutes with their unit. */
export function formatMinutes(minutes: number): string {
  return `${Math.round(minutes)} min`;
}

/** Minutes for a figure: withheld reads "fewer than 10", a missing value reads "No figure yet" (never 0). */
export function formatMinutesFigure(figure: Count): string {
  if (figure.suppressed === true) return WITHHELD;
  if (figure.value === null) return NO_FIGURE;
  return formatMinutes(figure.value);
}
