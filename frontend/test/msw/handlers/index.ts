import type { RequestHandler } from 'msw';
import { authHandlers } from './auth';
import { boardHandlers } from './board';
import { linkHandlers } from './links';
import { profileHandlers } from './profile';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here.
export const handlers: RequestHandler[] = [...authHandlers, ...boardHandlers, ...linkHandlers, ...profileHandlers];
