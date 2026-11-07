// The printed check-in code of a service as the page reads it (DEC-1346). Pure. The matrix is the QR code, one string of
// 0 and 1 per row; the page draws it itself, so no image or script from another origin is loaded.

export type CheckinCode = { service: string; url: string; size: number; rows: string[] };

export class CheckinCodeParseError extends Error {
  constructor() {
    super('The check-in code is not in the shape the page knows.');
    this.name = 'CheckinCodeParseError';
  }
}

const MAX_SIZE = 177; // QR version 40

export function parseCheckinCode(value: unknown): CheckinCode {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new CheckinCodeParseError();
  const { service, url, size, rows } = value as Record<string, unknown>;
  if (typeof service !== 'string' || service === '') throw new CheckinCodeParseError();
  if (typeof url !== 'string' || !url.startsWith('https://')) throw new CheckinCodeParseError();
  if (typeof size !== 'number' || !Number.isInteger(size) || size < 21 || size > MAX_SIZE) throw new CheckinCodeParseError();
  if (!Array.isArray(rows) || rows.length !== size) throw new CheckinCodeParseError();
  for (const row of rows) {
    if (typeof row !== 'string' || row.length !== size || /[^01]/.test(row)) throw new CheckinCodeParseError();
  }
  return { service, url, size, rows: rows as string[] };
}

/** The matrix as one SVG path: a bar for each run of dark cells in a row. */
export function matrixPath(rows: readonly string[]): string {
  const parts: string[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (row[x] !== '1') {
        x += 1;
        continue;
      }
      let end = x;
      while (end < row.length && row[end] === '1') end += 1;
      parts.push(`M${x} ${y}h${end - x}v1h-${end - x}z`);
      x = end;
    }
  });
  return parts.join('');
}
