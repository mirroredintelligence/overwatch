import { DiffPair } from '@/components/blocks/DiffPair';
import type { SettingJson, SettingSpec } from '@/lib/tenantAdmin/views';
import { humaniseKey, valueText } from '@/lib/tenantAdmin/words';
import styles from './ConfigDiff.module.css';

// The difference between two versions of the settings (TEN-076, board A3): one card per key that changed, what
// it was and what it is in labelled Was and Now groups. A list of codes is two sets of chips with the additions
// marked (DiffPair) and said in words. A key that is not overridden on one side is said as its default, in
// words, so a reader does not mistake "not set" for zero. A clinical key is marked in a word (and a border), an
// operational one in a word and a dashed tag, never by colour alone. Values are text: React escapes them.

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

/** The codes on one side: what is set, else the default, else none. */
function sideCodes(spec: SettingSpec | undefined, values: Readonly<Record<string, SettingJson>>, key: string): string[] {
  const raw = key in values ? values[key] : (spec?.default ?? null);
  return Array.isArray(raw) ? raw.map(String) : [];
}

function joined(items: readonly string[]): string {
  if (items.length < 2) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

function inWords(was: readonly string[], now: readonly string[]): string {
  const added = now.filter((item) => !was.includes(item));
  const removed = was.filter((item) => !now.includes(item));
  const parts = [added.length > 0 ? `added ${joined(added)}` : '', removed.length > 0 ? `removed ${joined(removed)}` : ''].filter((part) => part !== '');
  return parts.length === 0 ? 'the list is in a different order.' : `${parts.join(', ')}.`;
}

function Side({ label, text }: { label: 'Was' | 'Now'; text: string }) {
  return (
    <div className={styles.side} role="group" aria-label={label}>
      <div className={styles.sideLabel} aria-hidden="true">
        {label}
      </div>
      <span className={styles.value}>{text}</span>
    </div>
  );
}

export function ConfigDiff({ changedKeys, before, after, specs }: ConfigDiffProps) {
  if (changedKeys.length === 0) return <p className={styles.none}>No setting changed.</p>;
  return (
    <div className={styles.diff}>
      <h2 className={styles.heading}>{`What changed · ${changedKeys.length} ${changedKeys.length === 1 ? 'setting' : 'settings'}`}</h2>
      {changedKeys.map((key) => {
        const spec = specs.find((s) => s.key === key);
        const clinical = spec?.safetyClass === 'clinical';
        const codes = spec?.kind === 'codes' || Array.isArray(after[key]) || Array.isArray(before[key]);
        const wasCodes = codes ? sideCodes(spec, before, key) : [];
        const nowCodes = codes ? sideCodes(spec, after, key) : [];
        return (
          <section key={key} className={`${styles.card} ${clinical ? styles.clinical : ''}`} aria-label={humaniseKey(key)}>
            <div className={styles.cardHead}>
              <span className={styles.name} aria-hidden="true">
                {humaniseKey(key)}
              </span>
              {spec === undefined ? null : (
                <span className={`${styles.tag} ${clinical ? styles.tagClinical : styles.tagDashed}`}>{clinical ? 'Clinical' : 'Operational'}</span>
              )}
            </div>
            {codes ? (
              <>
                <DiffPair was={wasCodes} now={nowCodes} />
                <p className={styles.words}>{`In words: ${inWords(wasCodes, nowCodes)}`}</p>
              </>
            ) : (
              <div className={styles.pair}>
                <Side label="Was" text={sideText(spec, before, key)} />
                <div className={styles.arrow} aria-hidden="true">
                  →
                </div>
                <Side label="Now" text={sideText(spec, after, key)} />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
