import type { RequestHandler } from 'msw';
import { bookingHandlers } from './bookings';
import { boardHandlers } from './board';
import { criteriaHandlers } from './criteria';
import { linkHandlers } from './links';
import { registrationHandlers, registrationStepHandlers } from './registrations';
import { staffHandlers } from './staff';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here.
export const handlers: RequestHandler[] = [
  ...boardHandlers,
  ...linkHandlers,
  ...bookingHandlers,
  ...staffHandlers,
  ...registrationHandlers,
  ...registrationStepHandlers,
  ...criteriaHandlers,
];
