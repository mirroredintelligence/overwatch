// Stub (red commit).
import type { FieldIssue } from './types';

export type OrganisationAnswers = {
  orgType?: string;
  contactName?: string;
  contactRole?: string;
  contact?: string;
};

export function validateOrganisation(_answers: OrganisationAnswers): FieldIssue[] {
  throw new Error('not implemented');
}
