// The BFF's answers for the lists the lead pages read, checked before the page shows them. A shape that is
// not the one expected is an error, never an empty list (H-330).

export class AnswerShapeError extends Error {
  constructor() {
    super('The answer was not the one expected.');
    this.name = 'AnswerShapeError';
  }
}

export function listOf(body: unknown, key: string): unknown[] {
  const value = (body as Record<string, unknown> | undefined)?.[key];
  if (!Array.isArray(value)) throw new AnswerShapeError();
  return value;
}

export function textOf(value: unknown): string {
  if (typeof value !== 'string') throw new AnswerShapeError();
  return value;
}
