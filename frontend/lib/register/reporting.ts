// Stub (red commit).
import type { FieldIssue } from './types';

export type ReportingAnswers = {
  /** The chip the applicant chose (not the back end's code: two chips share `free-beds`). */
  counts?: string;
  usualLow?: string;
  usualHigh?: string;
  cadence?: string;
  channel?: string;
  holderName?: string;
  contactMobile?: string;
  contactEmail?: string;
};

export type ApiAnswers = { wanted?: boolean; name?: string; address?: string; connection?: string; dataType?: string };

export function measureCodeOf(_counts: string): string | null {
  throw new Error('not implemented');
}

export function validateReporting(_answers: ReportingAnswers): FieldIssue[] {
  throw new Error('not implemented');
}

export function validateApi(_answers: ApiAnswers): FieldIssue[] {
  throw new Error('not implemented');
}

export function reportingValues(_body: Record<string, unknown>): Record<string, unknown> {
  throw new Error('not implemented');
}

export function apiValues(_body: Record<string, unknown>): Record<string, unknown> {
  throw new Error('not implemented');
}
