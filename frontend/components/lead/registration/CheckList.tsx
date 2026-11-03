import type { AutomaticCheck } from '@/lib/registration/types';
import styles from './CheckList.module.css';

// The automatic checks of one registration (board RevChecks, Rev1). Each is a shape and a word: a tick and
// "Passed", or a triangle and "Needs attention", never colour alone. The back end words every check, including
// the address check that passes when the organisation has no area limit (DEC-1323); nothing here works a check out.
// A check that needs attention is information for the call-back, never a gate: the back end's list of what is
// missing before Approve is the only gate.

/** The first check that needs attention, in the order the back end gave; the queue card shows this one. */
export function firstProblem(checks: readonly AutomaticCheck[]): AutomaticCheck | undefined {
  return checks.find((check) => !check.ok);
}

export function CheckList({ checks }: { checks: readonly AutomaticCheck[] }) {
  return (
    <section className={styles.section} aria-labelledby="registration-checks-heading">
      <h2 id="registration-checks-heading" className={styles.heading}>
        Checks the system did
      </h2>
      {checks.length === 0 ? (
        <p className={styles.empty}>No checks were run.</p>
      ) : (
        <ul className={styles.list}>
          {checks.map((check) => (
            <li key={check.key} className={styles.item} data-ok={check.ok}>
              <span className={check.ok ? styles.pass : styles.problem} aria-hidden="true">
                {check.ok ? '✓' : '▲'}
              </span>
              <span className={styles.text}>
                <span className={styles.srOnly}>{check.ok ? 'Passed:' : 'Needs attention:'}</span>
                <span>{check.label}</span>
                {!check.ok && check.action !== undefined ? (
                  <>
                    {' '}
                    <strong>{check.action}</strong>
                  </>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
