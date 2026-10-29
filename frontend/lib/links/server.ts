// Red stub (DEC-010): the names and signatures the tests use. Not built yet.
export class LinkApiError extends Error {
  readonly kind: 'unavailable' | 'bad-answer';
  constructor(kind: 'unavailable' | 'bad-answer') {
    super('not built');
    this.kind = kind;
  }
}
export function backendRoot(_value: string | undefined): string {
  throw new Error('not built: backendRoot');
}
export async function callLinkApi(_options: unknown): Promise<{ status: number; body: unknown; retryAfter?: string }> {
  throw new Error('not built: callLinkApi');
}
export async function readLink(_token: string, _host: string | null): Promise<unknown> {
  throw new Error('not built: readLink');
}
export function publicReply(_status: number, _body: unknown): { status: number; body: unknown } {
  throw new Error('not built: publicReply');
}
