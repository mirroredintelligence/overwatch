// Red stub (DEC-010): the names and signatures the tests use. Not built yet.
export const LINK_CSRF_COOKIE = 'diucs_link_csrf';
export function linkCsrfPath(_token: string): string {
  throw new Error('not built: linkCsrfPath');
}
export async function issueLinkCsrf(_token: string, _value: string): Promise<void> {
  throw new Error('not built: issueLinkCsrf');
}
export function checkLinkCsrf(_request: Request, _token: string): boolean {
  throw new Error('not built: checkLinkCsrf');
}
