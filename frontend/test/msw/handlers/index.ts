import type { RequestHandler } from 'msw';
import { advisorHandlers } from './advisor';
import { bookingHandlers } from './bookings';
import { boardHandlers } from './board';
import { linkHandlers } from './links';
import { profileHandlers } from './profile';
import { tenantDataHandlers } from './tenantData';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here. The token exchange (./auth) is not here: the tests
// that sign someone in add it.
export const handlers: RequestHandler[] = [
  ...boardHandlers,
  ...linkHandlers,
  ...bookingHandlers,
  ...advisorHandlers,
  ...profileHandlers,
  ...tenantDataHandlers,
];
