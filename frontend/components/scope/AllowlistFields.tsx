import { checkLabels, labelsFor } from '@/lib/networkAdmin/fieldLabels';
import type { Scope } from '@/lib/networkAdmin/views';
import { SCOPE_WORD } from '@/lib/networkAdmin/words';
import styles from '../admin/admin.module.css';

// The fields that leave an organisation for a network, in plain words (TEN-081, design N2: SharingFields).
// The list is rendered from the allowlist the back end returns (`fields`: the DTO field names of
// `domain/rules/projection.py`), through the table of sentences in `lib/networkAdmin/fieldLabels.ts`. A field
// the back end sends that has no sentence cannot be described, so nothing is listed and the page says so
// (fail closed): an administrator is never asked to approve a list that is not the whole list. The internal
// references are never listed and no field's own name is ever printed.

export function AllowlistFields({ scope, fields }: { scope: Scope; fields: readonly string[] }) {
  if (checkLabels(scope, fields).unlabelled.length > 0) {
    return (
      <p role="alert" className={styles.problem}>
        We could not list the fields that are shared. Do not approve this until it is fixed.
      </p>
    );
  }
  return (
    <ul className={styles.list} data-el="SHARE-FIELDS-LIST" aria-label={`Fields shared: ${SCOPE_WORD[scope].toLowerCase()}`}>
      {labelsFor(scope, fields).map((label) => (
        <li key={label}>{label}</li>
      ))}
    </ul>
  );
}

/** True when every field the back end sends for this kind has a sentence, so the whole list can be shown. */
export const canListFields = (scope: Scope, fields: readonly string[]): boolean => checkLabels(scope, fields).unlabelled.length === 0;
