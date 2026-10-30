import { beforeEach } from 'vitest';
import { registrationHandlers } from './handlers/registration';
import { server } from './server';

// The applicant's registration handlers (W23 to W27) answer the same paths as the reviewer's
// (W28, W29) with other payloads, so they are not defaults: a test of an applicant screen calls this.
export function withApplicantHandlers(): void {
  beforeEach(() => {
    server.use(...registrationHandlers);
  });
}
