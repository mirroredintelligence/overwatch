import { startSignIn } from '@/lib/auth/flow';

export const POST = (request: Request) => startSignIn(request);
