import type { Parameters } from '@/lib/fhir/types';

// The week summary (W41) as the screens read it, from the back end's `$week-summary` (R12, U35). The week
// is the back end's Monday-to-Sunday week: `ending` is its Sunday. Pure: no I/O and no clock, except the
// one default `weekEndingDefault` takes as an argument.

export type Figure = { value: number | null; suppressed: boolean };

export type WeekSummary = {
  from: string;
  to: string;
  referrals: Figure;
  bestFitUnavailablePct: Figure;
  onTimePct: Figure;
  medianMinutesToConfirmed: Figure;
  /** The sum of the channels, withheld when any channel is withheld. */
  updates: Figure;
  /** The tenant's minutes per avoided call. The back end does not hold it yet (TEN-026), so this is null. */
  minutesPerCall: number | null;
};

const DAY_MS = 86_400_000;
const SUNDAY = 0;

function parseDay(iso: string): Date {
  const day = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== iso) throw new Error('not a date');
  return day;
}

function addDays(iso: string, days: number): string {
  return new Date(parseDay(iso).getTime() + days * DAY_MS).toISOString().slice(0, 10);
}

/** The Sunday that ends the last complete Monday-to-Sunday week before `now` (UTC date). */
export function weekEndingDefault(now: Date): string {
  const today = now.toISOString().slice(0, 10);
  const dow = now.getUTCDay();
  return addDays(today, -(dow === SUNDAY ? 7 : dow));
}

/** The Monday that starts the week ending on `ending`. Throws unless `ending` is a Sunday. */
export function weekStartFor(ending: string): string {
  if (parseDay(ending).getUTCDay() !== SUNDAY) throw new Error('the week must end on a Sunday');
  return addDays(ending, -6);
}

type Part = { name?: unknown; valueBoolean?: unknown; valueInteger?: unknown; valueDecimal?: unknown; part?: Part[]; valueDate?: unknown };

function partsOf(parameter: Part | undefined, name: string): Part[] {
  if (!parameter) throw new Error(`the back end sent no ${name}`);
  return parameter.part ?? [];
}

function figureOf(parameter: Part | undefined, name: string): Figure {
  const parts = partsOf(parameter, name);
  const suppressed = parts.find((p) => p.name === 'suppressed')?.valueBoolean === true;
  if (suppressed) return { value: null, suppressed: true };
  const value = parts.find((p) => p.name === 'value');
  const raw = value?.valueInteger ?? value?.valueDecimal;
  return { value: typeof raw === 'number' ? raw : null, suppressed: false };
}

function findParameter(parameters: Part[], name: string): Part | undefined {
  return parameters.find((p) => p.name === name);
}

/** The week's figures from the back end's Parameters. A missing figure is refused, never assumed. */
export function summaryFromParameters(body: unknown, minutesPerCall: number | null = null): WeekSummary {
  const resource = body as Partial<Parameters> | undefined;
  if (!resource || resource.resourceType !== 'Parameters' || !Array.isArray(resource.parameter)) {
    throw new Error('the back end sent no week summary');
  }
  const parameters = resource.parameter as Part[];
  const weekStart = findParameter(parameters, 'weekStart')?.valueDate;
  if (typeof weekStart !== 'string') throw new Error('the back end sent no week start');
  const channels = findParameter(parameters, 'updatesByChannel');
  const channelFigures = partsOf(channels, 'updates').map((channel) => figureOf(channel, 'channel'));
  const updates: Figure = channelFigures.some((f) => f.suppressed)
    ? { value: null, suppressed: true }
    : { value: channelFigures.reduce((sum, f) => sum + (f.value ?? 0), 0), suppressed: false };
  return {
    from: weekStart,
    to: addDays(weekStart, 6),
    referrals: figureOf(findParameter(parameters, 'referrals'), 'referrals'),
    bestFitUnavailablePct: figureOf(findParameter(parameters, 'bestFitUnavailablePct'), 'bestFitUnavailablePct'),
    onTimePct: figureOf(findParameter(parameters, 'onTimePct'), 'onTimePct'),
    medianMinutesToConfirmed: figureOf(findParameter(parameters, 'medianMinutesToConfirmed'), 'medianMinutesToConfirmed'),
    updates,
    minutesPerCall,
  };
}

/**
 * The time-back line (W41). While the minutes per call are unset the line keeps "[x]" and says the
 * baseline is not measured; once they are set the estimate shows its sum. A withheld count has no estimate.
 */
export function timeBack(updates: Figure, minutesPerCall: number | null): { sentence: string; estimate: string | null } {
  if (updates.suppressed || updates.value === null) {
    return { sentence: 'Fewer than 10 updates by text, app or email.', estimate: null };
  }
  if (minutesPerCall === null) {
    return {
      sentence: `${updates.value} updates by text, app or email. Each replaces about one phone call of [x] minutes.`,
      estimate: 'Estimate until we measure the baseline.',
    };
  }
  const total = updates.value * minutesPerCall;
  return {
    sentence: `${updates.value} updates by text, app or email. Each replaces about one phone call of ${minutesPerCall} minutes.`,
    estimate: `about ${total.toLocaleString('en-GB')} minutes (${updates.value} × ${minutesPerCall})`,
  };
}
