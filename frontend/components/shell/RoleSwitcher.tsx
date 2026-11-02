import styles from './RoleSwitcher.module.css';

// The role chip (DEC-1324): a person whose groups give more than one staff role can sign in again as
// another of them. Each choice posts the start of a sign-in with that role; the back end gives the
// role only if the person's groups give it, so the list here is a convenience and never the check.
// No script: a native disclosure opens the menu, and the animation is CSS (none for reduced motion).

export const STAFF_ROLE_WORDS: Readonly<Record<string, string>> = {
  'tenant-admin': 'Tenant administrator',
  'network-admin': 'Network administrator',
  lead: 'Shift lead',
  clinical: 'Clinical lead',
  advisor: 'Advisor',
  owner: 'Criteria owner',
  exec: 'Planning',
  audit: 'Audit',
};

export function staffRoleWord(role: string): string {
  return STAFF_ROLE_WORDS[role] ?? role;
}

export function RoleSwitcher({ current, roles }: { current: string; roles: readonly string[] }) {
  return (
    <details className={styles.switcher} data-el="ROLE-SWITCHER">
      <summary className={styles.chip}>
        <span>{staffRoleWord(current)}</span>
        <span aria-hidden="true" className={styles.caret}>
          ▾
        </span>
      </summary>
      <form className={styles.menu} method="post" action="/api/bff/auth/entra/start" aria-label="Sign in as another role">
        <p className={styles.hint}>Sign in again as:</p>
        {roles.map((role) => (
          <button
            key={role}
            type="submit"
            name="role"
            value={role}
            className={role === current ? styles.itemCurrent : styles.item}
            aria-current={role === current ? 'true' : undefined}
          >
            {staffRoleWord(role)}
          </button>
        ))}
      </form>
    </details>
  );
}
