// The staff roles a directory group may be mapped to, in the words the product uses for them (the role
// names of the lead's, clinical and planning pages). The administrator role is not here: a group cannot be
// mapped to it, the first administrator is invited by the platform operator (DEC-1007 item 4).

export const MAPPABLE_ROLE_WORDS: readonly [string, string][] = [
  ['advisor', 'Advisor'],
  ['clinical', 'Clinical lead'],
  ['lead', 'Shift lead'],
  ['owner', 'Criteria owner'],
  ['exec', 'Planning'],
  ['audit', 'Audit'],
];
