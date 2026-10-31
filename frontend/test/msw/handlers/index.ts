import type { RequestHandler } from 'msw';
import { advisorHandlers } from './advisor';
import { bookingHandlers } from './bookings';
import { boardHandlers } from './board';
import { criteriaHandlers } from './criteria';
import { leadHandlers } from './lead';
import { linkHandlers } from './links';
import { ownScopeHandlers } from './networkBff';
import { profileHandlers } from './profile';
import { registrationHandlers as reviewerRegistrationHandlers, registrationStepHandlers } from './registrations';
import { reporterHandlers } from './reporter';
import { staffHandlers } from './staff';
import { tenantDataHandlers } from './tenantData';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here. `registrations` is the reviewer's (W28, W29); the
// applicant's (`registration`, W23 to W27) answer the same paths, so tests opt in: test/msw/applicant.ts.
// The token exchange (./auth) is not here: the tests that sign someone in add it.
export const handlers: RequestHandler[] = [
  ...boardHandlers,
  ...linkHandlers,
  ...bookingHandlers,
  ...advisorHandlers,
  ...staffHandlers,
  ...reviewerRegistrationHandlers,
  ...registrationStepHandlers,
  ...criteriaHandlers,
  ...leadHandlers,
  ...reporterHandlers,
  ...profileHandlers,
  ...tenantDataHandlers,
  ...ownScopeHandlers,
];
