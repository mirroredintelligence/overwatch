// DEC-010 stub (W28 red).
import type { ScopeEntry, ScopeFlag } from './types';

export function canInvite(_entry: ScopeEntry): boolean {
  return false;
}
export function reasonRequired(_flag: ScopeFlag): boolean {
  return true;
}
export function scopeReasonError(_flag: ScopeFlag, _reason: string): string | null {
  return null;
}
export function categoryLabel(code: string): string {
  return code;
}
