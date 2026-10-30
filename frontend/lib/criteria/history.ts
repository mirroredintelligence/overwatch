// DEC-010 stub (W31 red).
import type { HistoryVersion } from './types';

export function mapHistory(_bundle: unknown): HistoryVersion[] {
  return [];
}

export function waitingVersion(_versions: readonly HistoryVersion[]): HistoryVersion | null {
  return null;
}
