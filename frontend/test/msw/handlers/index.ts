import type { RequestHandler } from 'msw';
import { boardHandlers } from './board';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here.
export const handlers: RequestHandler[] = [...boardHandlers];
