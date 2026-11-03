'use client';

import { useEffect, useRef } from 'react';
import { staffRoleWord } from '@/lib/shell/roleWords';
import styles from './RoleSwitcher.module.css';

// The role chip (DEC-1324): a person whose groups give more than one staff role can sign in again as
// another of them. Each choice is a link to the start of a sign-in with that role (a link, not a form, so
// the page's form-action policy does not limit it); the back end gives the
// role only if the person's groups give it, so the list here is a convenience and never the check.
// A native disclosure opens the menu (Enter or Space on the chip); Escape, a click elsewhere or choosing a
// role closes it. The animation is CSS (none for reduced motion).

export { STAFF_ROLE_WORDS, staffRoleWord } from '@/lib/shell/roleWords';

export function RoleSwitcher({
  current,
  roles,
  words,
  align = 'end',
}: {
  current: string;
  roles: readonly string[];
  /** Words for roles, where the page names them differently from the default (a plain object, so a server page can pass it). */
  words?: Readonly<Record<string, string>>;
  /** Which edge of the chip the menu lines up with: `end` in a header's right-hand corner, `start` at its left. */
  align?: 'start' | 'end';
}) {
  const box = useRef<HTMLDetailsElement>(null);
  const word = (role: string) => words?.[role] ?? staffRoleWord(role);

  useEffect(() => {
    const close = () => {
      if (box.current?.open) box.current.open = false;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || !box.current?.open) return;
      close();
      box.current.querySelector('summary')?.focus();
    };
    const onPointer = (event: PointerEvent) => {
      if (box.current?.open && event.target instanceof Node && !box.current.contains(event.target)) close();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, []);

  return (
    <details ref={box} className={styles.switcher} data-el="ROLE-SWITCHER">
      <summary className={styles.chip}>
        <span>{word(current)}</span>
        <span aria-hidden="true" className={styles.caret}>
          ▾
        </span>
      </summary>
      <div className={`${styles.menu} ${align === 'start' ? styles.menuStart : ''}`} role="group" aria-label="Sign in as another role">
        <p className={styles.hint}>Sign in again as:</p>
        {roles.map((role) => (
          <a
            key={role}
            href={`/api/bff/auth/entra/start?role=${encodeURIComponent(role)}`}
            className={role === current ? styles.itemCurrent : styles.item}
            aria-current={role === current ? 'true' : undefined}
          >
            {word(role)}
          </a>
        ))}
      </div>
    </details>
  );
}
