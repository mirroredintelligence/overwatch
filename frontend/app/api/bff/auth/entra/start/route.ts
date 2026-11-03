import { startSignIn, startSignInFromLink } from '@/lib/auth/flow';

// POST: the sign-in button's form. GET: the links that start a sign-in for a role or a tenant.
export const POST = (request: Request) => startSignIn(request);
export const GET = (request: Request) => startSignInFromLink(request);
