import { acceptsLine, doesNotAcceptLine } from '@/lib/criteria/model';
import type { CriteriaValues } from '@/lib/criteria/types';
import styles from '@/components/lead/lead.module.css';

// What advisors will see if the change goes live, and what changed (W30, ui-screens CriteriaOwner
// screen 5). The words are the same ones the advisor sees; the diff is computed by diffCriteria.

export function CriteriaPreview({ serviceName, values, changes }: { serviceName: string; values: CriteriaValues; changes: string[] }) {
  return (
    <section>
      <h1 className={styles.heading}>Preview</h1>
      <h2 className={styles.section}>What advisors will see</h2>
      <p className={styles.name}>{serviceName}</p>
      <p>{acceptsLine(values)}</p>
      <p>{doesNotAcceptLine(values)}</p>
      <h2 className={styles.section}>What changed</h2>
      {changes.length === 0 ? (
        <p>Nothing changed.</p>
      ) : (
        <ul className={styles.steps}>
          {changes.map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
