import type { RequestHandler } from 'msw';
import { boardHandlers } from './board';
import { linkHandlers } from './links';

// Default handlers for every test. Feature tasks add their handlers in
// test/msw/handlers/<area>.ts and list them here.
import { reporterHandlers } from './reporter';

export const handlers: RequestHandler[] = [...boardHandlers, ...linkHandlers, ...reporterHandlers];
