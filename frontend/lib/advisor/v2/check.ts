// The answer to "does this patient fit this one service" (DEC-1377). The back end runs the same hard criteria as the
// find (check_hard_criteria); the browser only reads the answer. Nothing about the patient is in it.

export type FitCheck = {
  serviceId: string;
  fits: boolean;
  /** Why not, in the back end's words. Empty when the patient fits. */
  reasons: string[];
  /** The needs the service lists as ones it takes, when the patient fits. */
  fitsNeeds: string[];
  warnings: string[];
  phone: string | null;
  figureUnavailable: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item !== '') : [];

/** The check, or null when the answer is not shaped like one. A missing `fits` is never read as a fit. */
export function parseCheck(body: unknown): FitCheck | null {
  if (!isRecord(body) || typeof body.fits !== 'boolean' || typeof body.serviceId !== 'string') return null;
  // Every reason must be a non-empty string: an item that is not one means the answer is not sound, so it is refused
  // rather than filtered (a filtered-out reason could turn a refusal into a fit).
  if (!Array.isArray(body.reasons) || !body.reasons.every((item) => typeof item === 'string' && item !== '')) return null;
  const reasons = strings(body.reasons);
  // A fit with reasons, or a non-fit with none, is not a sound answer: refuse it rather than show it.
  if (body.fits === reasons.length > 0) return null;
  return {
    serviceId: body.serviceId,
    fits: body.fits,
    reasons,
    fitsNeeds: strings(body.fitsNeeds),
    warnings: strings(body.warnings),
    phone: typeof body.phone === 'string' && body.phone !== '' ? body.phone : null,
    figureUnavailable: body.figureUnavailable === true,
  };
}
