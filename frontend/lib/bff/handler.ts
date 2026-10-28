// Stub for the red commit (DEC-010). Replaced in the implement commit.
import type { Role, Session } from '@/lib/auth/session';

export type BffOptions = { roles?: Role[]; csrf?: boolean };

export type BffHandler<C = unknown> = (
  request: Request,
  session: Session,
  context: C,
) => Response | Promise<Response>;

export function withBff<C = unknown>(
  _handler: BffHandler<C>,
  _options?: BffOptions,
): (request: Request, context: C) => Promise<Response> {
  return async () => {
    throw new Error('withBff is not implemented yet');
  };
}
