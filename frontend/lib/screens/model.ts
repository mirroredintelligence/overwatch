// Red-commit stub (DEC-010).
export const CODE_REQUIRED_MESSAGE = '';
export const CODE_LENGTH_MESSAGE = '';
export const NAME_REQUIRED_MESSAGE = '';
export const SCREEN_LABEL_MAX = 0;
export type FieldResult<T> = { ok: true; value: T } | { ok: false; error: string };
export const formatCode = (code: string): string => code;
export const parseCode = (input: string): FieldResult<string> => ({ ok: true, value: input });
export const parseName = (input: string): FieldResult<string> => ({ ok: true, value: input });
export const parseLocation = (input: string): FieldResult<string | null> => ({ ok: true, value: input });
