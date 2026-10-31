import type { OptionView } from '@/lib/advisor/options';
import { durationText } from '@/lib/board/format';

// The words of the compare view's rows (RadarWeb 2). Pure. Each is built from the option as the back end
// sent it; a figure the back end did not send is "Not recorded", never a guess, and the two rows that
// need a service's round (what a visit adds to it, which patients are near) are "Not available" until
// the back end has that (see the report: no endpoint offers it).

export const NOT_RECORDED = 'Not recorded';
export const NOT_AVAILABLE = 'Not available';

/** "4 referrals in the next 2 hrs", "+2 over", or "Phone to confirm" when no figure came. */
export function freeText(option: OptionView): string {
  if (option.status === 'over-capacity' && option.overBy !== null) return `+${option.overBy} over`;
  if (option.effectiveAvailable === null) return 'Phone to confirm';
  const unit = (option.unitLabel ?? '').replace(/ free$/, '').trim();
  return unit === '' ? String(option.effectiveAvailable) : `${option.effectiveAvailable} ${unit}`;
}

/** "About 35 to 50 min" from the range the back end sent. */
export function reachText(option: OptionView): string {
  if (option.travelText === null) return NOT_RECORDED;
  return option.travelText.charAt(0).toUpperCase() + option.travelText.slice(1);
}

/** "9 min", "2 hrs 10 min", with the warning when the figure is too old to lean on. */
export function ageText(option: OptionView): string {
  if (option.dataAgeSeconds === null) return 'Not known';
  const age = durationText(Math.floor(option.dataAgeSeconds / 60));
  return option.staleWarning ? `${age}. Over 2 hrs old: consider phoning.` : age;
}
