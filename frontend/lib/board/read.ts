import type { Session } from '@/lib/auth/session';
import type { Board } from './types';

// Stub (DEC-010).
export const BOARD_ROLES: readonly Session['role'][] = [];

export function canReadBoard(role: Session['role']): boolean {
  void role;
  return false;
}

export async function readBoard(session: Pick<Session, 'backendToken'>): Promise<Board> {
  void session;
  return { entries: [], pressure: '', allLimitedOrWorse: false, generatedAt: '', organisation: null };
}
