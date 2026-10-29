import { completeSignIn } from '@/lib/auth/flow';

export const GET = (request: Request) => completeSignIn(request);
