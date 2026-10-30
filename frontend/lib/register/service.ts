// Stub (red commit).
export type ServiceAnswers = {
  category?: string;
  referralMethods?: string[];
  spoaPhone?: string;
  acceptingDays?: string[];
  acceptingStart?: string;
  acceptingEnd?: string;
  needs?: string[];
  ageMin?: string;
  ageMax?: string | null;
  excludedNeeds?: string[];
  noExclusions?: boolean;
  ownerRole?: string;
  ownerEmail?: string;
  reviewBy?: string;
  districts?: string[];
};

export function normaliseDistrict(_input: string): string | null {
  throw new Error('not implemented');
}

export function validateService(_answers: ServiceAnswers, _context: { fixedSite: boolean | undefined; today: string }): import('./types').FieldIssue[] {
  throw new Error('not implemented');
}

export function serviceValues(_body: Record<string, unknown>, _serviceName: string): Record<string, unknown> {
  throw new Error('not implemented');
}
