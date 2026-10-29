// Red stub (DEC-010): the names and signatures the tests use. Not built yet.
import type { LinkAnswer, LinkAnswered } from './model';
export type AnswerOutcome =
  | { kind: 'recorded'; answered: LinkAnswered }
  | { kind: 'out-of-range'; usualMin: number; usualMax: number }
  | { kind: 'send-number' }
  | { kind: 'gone' }
  | { kind: 'rate-limited' }
  | { kind: 'failed' };
export async function armLink(_token: string): Promise<'ready' | 'gone' | 'unavailable'> {
  throw new Error('not built: armLink');
}
export async function sendAnswer(_token: string, _csrf: string, _answer: LinkAnswer): Promise<AnswerOutcome> {
  throw new Error('not built: sendAnswer');
}
export async function requestRenew(_token: string): Promise<'accepted' | 'rate-limited' | 'failed'> {
  throw new Error('not built: requestRenew');
}
