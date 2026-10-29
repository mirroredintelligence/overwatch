// Stub for the red commit (DEC-010): the content security policy (S01).

export function buildCsp(nonce: string, dev: boolean): string {
  throw new Error(`S01: buildCsp is not built yet (${nonce.length}, ${dev})`);
}

export function securityHeaders(): Record<string, string> {
  throw new Error('S01: securityHeaders is not built yet');
}
