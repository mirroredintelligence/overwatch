// The staff roles in words, for the role chip (DEC-1324). A plain module, so server and client components can
// both use it. The staff header's own labels (lib/shell/nav.ts) win where it has one; these are the rest.

export const STAFF_ROLE_WORDS: Readonly<Record<string, string>> = {
  'tenant-admin': 'Tenant administrator',
  'network-admin': 'Network administrator',
  lead: 'Shift lead',
  clinical: 'Clinical lead',
  advisor: 'Advisor',
  owner: 'Criteria owner',
  exec: 'Planning',
  audit: 'Audit',
  'analytics-user': 'Analytics User',
  'advisor-v2': 'Advisor v2',
};

export function staffRoleWord(role: string): string {
  return STAFF_ROLE_WORDS[role] ?? role;
}
