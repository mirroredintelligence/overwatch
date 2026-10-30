// Stub (red commit): the behaviour is written in the tests first.

export type MobileProblem = 'empty' | 'invalid';

export function normaliseMobile(_input: string): string | null {
  throw new Error('not implemented');
}

export function mobileProblem(_input: string): MobileProblem | null {
  throw new Error('not implemented');
}

export function maskMobile(_mobile: string): string {
  throw new Error('not implemented');
}
