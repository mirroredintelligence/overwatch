// Stub for the red commit (DEC-010). Replaced in the implement commit.

export const CSRF_COOKIE = 'diucs_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';

export async function issueCsrf(): Promise<string> {
  throw new Error('issueCsrf is not implemented yet');
}

export function checkCsrf(_request: Request): boolean {
  throw new Error('checkCsrf is not implemented yet');
}

export async function clearCsrf(): Promise<void> {
  throw new Error('clearCsrf is not implemented yet');
}
