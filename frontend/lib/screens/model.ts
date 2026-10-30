// The rules of what a shift lead types to connect a wall screen, in one place so the page and the
// BFF check the same thing (the page for the person's sake, the BFF because the page is not trusted).
// The words are the prompt's (W08).

export const CODE_REQUIRED_MESSAGE = 'Enter the code shown on the screen';
export const CODE_LENGTH_MESSAGE = 'The code has 6 numbers';
export const NAME_REQUIRED_MESSAGE = 'Enter a name for the screen';
/** The longest a screen's name or place may be: the back end's own limit (`SCREEN_LABEL_MAX`). */
export const SCREEN_LABEL_MAX = 60;
export const TOO_LONG_MESSAGE = `Use ${SCREEN_LABEL_MAX} characters or fewer.`;
export const NOT_PRINTABLE_MESSAGE = 'Use letters, numbers and punctuation only.';

const CODE = /^[0-9]{6}$/;
// Control characters, DEL and the C1 range: never printable.
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;

export type FieldResult<T> = { ok: true; value: T } | { ok: false; error: string };

/** A six-digit code as the wall shows it: two groups of three. Nothing for anything that is not a code. */
export function formatCode(code: string): string {
  return typeof code === 'string' && CODE.test(code) ? `${code.slice(0, 3)} ${code.slice(3)}` : '';
}

/** The code as typed or as shown, with any spaces, to six digits. */
export function parseCode(input: unknown): FieldResult<string> {
  if (typeof input !== 'string') return { ok: false, error: CODE_REQUIRED_MESSAGE };
  const code = input.replace(/\s/g, '');
  if (code === '') return { ok: false, error: CODE_REQUIRED_MESSAGE };
  return CODE.test(code) ? { ok: true, value: code } : { ok: false, error: CODE_LENGTH_MESSAGE };
}

function label(input: string): FieldResult<string> {
  const text = input.trim();
  if (text.length > SCREEN_LABEL_MAX) return { ok: false, error: TOO_LONG_MESSAGE };
  if (CONTROL.test(text)) return { ok: false, error: NOT_PRINTABLE_MESSAGE };
  return { ok: true, value: text };
}

export function parseName(input: unknown): FieldResult<string> {
  if (typeof input !== 'string' || input.trim() === '') return { ok: false, error: NAME_REQUIRED_MESSAGE };
  return label(input);
}

/** An empty or missing place is no place; a place that is not text is refused. */
export function parseLocation(input: unknown): FieldResult<string | null> {
  if (input === undefined || input === null) return { ok: true, value: null };
  if (typeof input !== 'string') return { ok: false, error: TOO_LONG_MESSAGE };
  if (input.trim() === '') return { ok: true, value: null };
  return label(input);
}
