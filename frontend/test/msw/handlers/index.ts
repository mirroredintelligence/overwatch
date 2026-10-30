import type { RequestHandler } from 'msw';
import { advisorHandlers } from './advisor';
import { bookingHandlers } from './bookings';
import { boardHandlers } from './board';
import { leadHandlers } from './lead';
import { linkHandlers } from './links';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here.
export const handlers: RequestHandler[] = [
  ...boardHandlers,
  ...linkHandlers,
  ...bookingHandlers,
  ...advisorHandlers,
  ...leadHandlers,
];
