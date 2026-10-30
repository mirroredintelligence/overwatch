// Red stub (lesson L139): every mapper answers a value that no test expects, so each test fails on
// its assertion. The implementation commit replaces this file.
import type { RegistrationStatusView, RegistrationView, ReviewRow } from './types';

// The stub passes the record through unchanged, so a leaking field fails the guard test.
export function viewFromRecord(record: unknown): RegistrationView | null {
  return record as RegistrationView;
}

export function reviewRowsFrom(view: RegistrationView): ReviewRow[] {
  void view;
  return [];
}

export function myServicesFrom(raw: unknown): { id: string; serviceName: string; state: string; detail: string }[] | null {
  void raw;
  return [];
}

export function statusFrom(raw: unknown): RegistrationStatusView | null {
  void raw;
  return { status: 'x', serviceName: 'x' };
}

export function addressesFrom(raw: unknown): { id: string; label: string }[] | null {
  void raw;
  return [];
}
