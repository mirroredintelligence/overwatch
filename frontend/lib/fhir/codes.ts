// The code system base the back end builds its extension and code URLs from (domain/codes.py,
// BASE_URL and code_system_url). The browser needs the same URLs to name what it sends, so this
// constant must move with the back end's; a test pins the value.

export const CODE_SYSTEM_BASE = 'https://diucs.example/CodeSystem/';

export function codeSystemUrl(name: string): string {
  return `${CODE_SYSTEM_BASE}${name}`;
}
