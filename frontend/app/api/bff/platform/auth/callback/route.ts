import { completeOperatorSignIn } from '@/lib/operator/flow';

export const GET = (request: Request) => completeOperatorSignIn(request);
