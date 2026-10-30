// DEC-010 stub (W28 red): the real browser client is written in the implement step.
export type BffResult<T> = { ok: true; data: T } | { ok: false; status: number; code: string };

export async function bffGet<T>(_path: string, _parse: (value: unknown) => T): Promise<BffResult<T>> {
  return { ok: false, status: 0, code: 'stub' };
}

export async function bffPost(_path: string, _body?: unknown, _key?: string): Promise<BffResult<unknown>> {
  return { ok: false, status: 0, code: 'stub' };
}
