import { startOperatorSignIn } from '@/lib/operator/flow';

export const POST = (request: Request) => startOperatorSignIn(request);
