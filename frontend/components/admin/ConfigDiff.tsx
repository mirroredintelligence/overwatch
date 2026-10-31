import type { SettingJson, SettingSpec } from '@/lib/tenantAdmin/views';
import { humaniseKey, valueText } from '@/lib/tenantAdmin/words';
import styles from './admin.module.css';

// The difference between two versions of the settings (TEN-076): one row per key that changed, what it was
// and what it is. A key that is not overridden on one side is said as its default, in words, so a reader
// does not mistake "not set" for zero. A clinical key is marked in a word (and a dashed border for the
// operational ones), never by colour alone. Values are text: React escapes them.

export type ConfigDiffProps = {
  changedKeys: readonly string[];
  before: Readonly<Record<string, SettingJson>>;
  after: Readonly<Record<string, SettingJson>>;
  specs: readonly SettingSpec[];
};

function sideText(spec: SettingSpec | undefined, values: Readonly<Record<string, SettingJson>>, key: string): string {
  const shape = spec ?? { kind: 'text' as const, unit: 'text' };
  if (key in values) return valueText(shape, values[key]);
  if (spec === undefined) return 'not set';
  return spec.default === null ? 'not set' : `${valueText(shape, spec.default)} (default)`;
}

export function ConfigDiff({ changedKeys, before, after, specs }: ConfigDiffProps) {
  if (changedKeys.length === 0) return <p className={styles.text}>No setting changed.</p>;
  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <caption>What changed</caption>
        <thead>
          <tr>
            <th scope="col">Setting</th>
            <th scope="col">Was</th>
            <th scope="col">Now</th>
            <th scope="col">Kind</th>
          </tr>
        </thead>
        <tbody>
          {changedKeys.map((key) => {
            const spec = specs.find((s) => s.key === key);
            return (
              <tr key={key}>
                <th scope="row">{humaniseKey(key)}</th>
                <td>{sideText(spec, before, key)}</td>
                <td>{sideText(spec, after, key)}</td>
                <td>
                  {spec === undefined ? (
                    '-'
                  ) : (
                    <span className={spec.safetyClass === 'clinical' ? `${styles.tag} ${styles.tagClinical}` : `${styles.tag} ${styles.tagDashed}`}>
                      {spec.safetyClass === 'clinical' ? 'Clinical' : 'Operational'}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
