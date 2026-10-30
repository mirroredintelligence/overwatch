import type { RequestHandler } from 'msw';
import { bookingHandlers } from './bookings';
import { boardHandlers } from './board';
import { linkHandlers } from './links';
import { registrationHandlers } from './registration';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here. Both sides of the W6E merge are kept: the
// booking handlers (integration/build) and the registration handlers (W23 to W27).
export const handlers: RequestHandler[] = [...boardHandlers, ...linkHandlers, ...bookingHandlers, ...registrationHandlers];
