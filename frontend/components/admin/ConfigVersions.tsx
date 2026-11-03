'use client';

import { useId, useMemo, useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import { buildDraft, effective, fieldId, hintFor, isChanged, labelFor, toField, type FieldValue } from '@/lib/tenantAdmin/draft';
import type { ConfigView, SettingSpec } from '@/lib/tenantAdmin/views';
import { Disclose } from './Disclose';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';
import look from './Disclose.module.css';
import mine from './ConfigVersions.module.css';

// The settings page (TEN-076, board A2): the settings in three groups beside the versions of the organisation's
// settings, which is in force, and a change drafted from it. A change is a new version. A clinical one needs two
// people who are not its author to approve it, and the page says so before anything is drafted. The draft is made
// from the version this page read (`basedOn`): a stale one is the back end's 409, and nothing here overwrites a
// newer version.

export const STATUS_WORD: Record<ConfigView['status'], string> = {
  draft: 'Draft',
  'pending-approval': 'Waiting for approval',
  current: 'In force',
  superseded: 'Replaced',
};

type GroupId = 'clinical' | 'operational' | 'words';

const GROUPS: { id: GroupId; title: string; about: string }[] = [
  { id: 'clinical', title: 'Clinical settings', about: 'A change needs two approvals from other people.' },
  { id: 'operational', title: 'Operational settings', about: 'A change needs one approval.' },
  { id: 'words', title: 'The names your messages use', about: 'Printed in texts and on screens.' },
];

/** The names are the operational settings that are text: what the messages and the screens call things. */
function groupOf(spec: SettingSpec): GroupId {
  if (spec.safetyClass === 'clinical') return 'clinical';
  return spec.kind === 'text' ? 'words' : 'operational';
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className={mine.page}>
      <PageHeader title="Settings" />
      {children}
    </main>
  );
}

export function ConfigVersions() {
  const versions = useAdminRead<{ versions: ConfigView[] }>('/api/bff/tenant/config/versions');
  const settings = useAdminRead<{ settings: SettingSpec[] }>('/api/bff/tenant/settings');
  const [saved, setSaved] = useState<{ version: number; required: number } | null>(null);
  // Bumped after a save and after a reload, so the form starts again from what is in force.
  const [round, setRound] = useState(0);

  if (versions.state.status === 'loading' || settings.state.status === 'loading') {
    return (
      <Shell>
        <Loading label="Loading the settings."><SkeletonRows count={3} /></Loading>
      </Shell>
    );
  }
  if (versions.state.status === 'failed' || settings.state.status === 'failed') {
    return (
      <Shell>
        <p role="alert" className={mine.problem}>
          We could not load the settings.
        </p>
      </Shell>
    );
  }
  const list = versions.state.data.versions;
  const inForce = list.find((v) => v.status === 'current') ?? null;

  return (
    <Shell>
      <div className={mine.layout}>
        <section aria-label="Settings" className={mine.main}>
          {saved !== null ? (
            <div role="status" className={mine.saved}>
              <p>
                {`Draft version ${saved.version} saved. It needs ${saved.required === 1 ? '1 approval' : `${saved.required} approvals from people other than you`}.`}
              </p>
              <p>
                <a className={mine.link} href={`/admin/config/${saved.version}`}>
                  {`Open version ${saved.version}`}
                </a>
              </p>
            </div>
          ) : null}
          <DraftForm
            key={`${inForce?.version ?? 0}-${round}`}
            specs={settings.state.data.settings}
            values={inForce?.values ?? {}}
            basedOn={inForce?.version ?? 0}
            onReload={() => {
              versions.reload();
              settings.reload();
              setSaved(null);
              setRound((n) => n + 1);
            }}
            onSaved={(result) => {
              setSaved(result);
              setRound((n) => n + 1);
              versions.reload();
            }}
          />
        </section>

        <aside aria-label="Versions" className={mine.aside}>
          <h2 className={mine.asideTitle}>Versions</h2>
          {list.length === 0 ? (
            <p className={mine.text}>No version of the settings has been made yet.</p>
          ) : (
            <ol className={mine.timeline} aria-label="Configuration versions">
              {list.map((v) => (
                <li key={v.version} className={mine.stop} data-status={v.status}>
                  <span className={mine.dot} aria-hidden="true" />
                  <span className={mine.stopBody}>
                    <a className={mine.stopLink} href={`/admin/config/${v.version}`} aria-label={`Version ${v.version}`}>
                      {`Version ${v.version}`}
                    </a>
                    <span className={`${mine.tag} ${mine.tagStatus}`}>{STATUS_WORD[v.status]}</span>
                    <span className={`${mine.tag} ${v.clinicalKeys.length > 0 ? mine.tagClinical : ''}`}>{v.clinicalKeys.length > 0 ? 'Clinical' : 'Operational'}</span>
                    <span className={mine.stopMeta}>{`${v.approvals} of ${v.approvalsRequired}`}</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
          <p className={mine.rule}>A change to a clinical setting is written as a draft and needs two other people. A change to anything else needs one.</p>
        </aside>
      </div>
    </Shell>
  );
}

type FormProps = {
  specs: SettingSpec[];
  values: Readonly<Record<string, ConfigView['values'][string]>>;
  basedOn: number;
  onReload: () => void;
  onSaved: (result: { version: number; required: number }) => void;
};

function DraftForm({ specs, values, basedOn, onReload, onSaved }: FormProps) {
  const initial = useMemo(() => Object.fromEntries(specs.map((s) => [s.key, toField(s, effective(s, values))])) as Record<string, FieldValue>, [specs, values]);
  const [fields, setFields] = useState<Record<string, FieldValue>>(initial);
  const [useDefault, setUseDefault] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [failure, setFailure] = useState<{ words: string; stale: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [openGroup, setOpenGroup] = useState<GroupId | null>(null);
  const [filter, setFilter] = useState('');
  const submitKey = useSubmitKey();
  const findId = useId();

  function edit(key: string, value: FieldValue) {
    submitKey.fresh();
    setFields((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure(null);
    const draft = buildDraft(specs, values, fields, useDefault);
    if (draft.problems.length > 0) {
      setErrors(draft.problems.map((p) => ({ field: fieldId(p.key), message: p.message })));
      // The first problem is in a group that may be shut: open it, so the person sees what to fix.
      const first = specs.find((spec) => spec.key === draft.problems[0]!.key);
      if (first !== undefined) {
        setFilter('');
        setOpenGroup(groupOf(first));
      }
      return;
    }
    setErrors([]);
    if (Object.keys(draft.changes).length === 0 && draft.removals.length === 0) {
      setFailure({ words: 'You have not changed anything.', stale: false });
      return;
    }
    setBusy(true);
    const result = await adminSend<{ version: number; approvalsRequired: number }>('POST', '/api/bff/tenant/config/drafts', { basedOn, changes: draft.changes, removals: draft.removals }, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      onSaved({ version: result.data.version, required: result.data.approvalsRequired });
      return;
    }
    setFailure(
      result.status === 409
        ? { words: 'The settings changed while you were working. Reload the page and try again.', stale: true }
        : { words: 'The draft could not be saved. Try again.', stale: false },
    );
  }

  const problemOf = (key: string) => errors.find((e) => e.field === fieldId(key))?.message ?? null;
  const words = filter.trim().toLowerCase();
  const matches = (spec: SettingSpec) => words === '' || labelFor(spec.key).toLowerCase().includes(words) || spec.key.toLowerCase().includes(words);
  // A setting is changed when the person has altered it from what is in force, or asked for its default.
  const changed = (spec: SettingSpec) => useDefault.has(spec.key) || isChanged(spec, toField(spec, effective(spec, values)), fields[spec.key] ?? '');
  const changedCount = specs.filter(changed).length;
  const clinicalChanged = specs.filter((spec) => spec.safetyClass === 'clinical' && changed(spec)).length;
  const shownCount = specs.filter(matches).length;

  const control = (spec: SettingSpec) => (
    <div key={spec.key} className={mine.setting} data-changed={changed(spec)}>
      <SettingControl
        spec={spec}
        values={values}
        value={fields[spec.key] ?? ''}
        error={problemOf(spec.key)}
        useDefault={useDefault.has(spec.key)}
        onChange={(value) => edit(spec.key, value)}
        onUseDefault={(on) => {
          submitKey.fresh();
          setUseDefault((current) => {
            const next = new Set(current);
            if (on) next.add(spec.key);
            else next.delete(spec.key);
            return next;
          });
        }}
      />
    </div>
  );

  return (
    <form className={mine.main} onSubmit={submit} noValidate aria-label="Draft a change">
      <ErrorSummary errors={errors} />
      <div className={mine.findRow}>
        <div className={mine.find}>
          <svg className={mine.findIcon} width="18" height="18" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
            <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <label htmlFor={findId} className={mine.findLabel}>
            Find a setting
          </label>
          <input
            id={findId}
            className={mine.findInput}
            type="search"
            autoComplete="off"
            placeholder="Find a setting"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
        <span className={mine.shown}>{words === '' ? plural(specs.length, 'setting', 'settings') : `${shownCount} of ${specs.length} shown`}</span>
      </div>

      <div className={mine.groups}>
        {GROUPS.map(({ id, title, about }) => {
          const all = specs.filter((s) => groupOf(s) === id);
          const shown = all.filter(matches);
          const count = all.filter(changed).length;
          // Typing opens the groups that match; a group that does not match stays shut and says "0 match".
          const isOpen = words !== '' ? shown.length > 0 : openGroup === id;
          return (
            <Disclose
              key={id}
              open={isOpen}
              onToggle={() => {
                if (words !== '') {
                  setFilter('');
                  setOpenGroup(id);
                } else setOpenGroup((now) => (now === id ? null : id));
              }}
              tone={id === 'clinical' ? 'clinical' : undefined}
              title={title}
              hint={about}
              aside={
                <>
                  {count > 0 ? <span className={mine.badge}>{`${count} changed`}</span> : null}
                  <span className={mine.count}>{words === '' ? plural(all.length, 'setting', 'settings') : `${shown.length} match`}</span>
                </>
              }
            >
              <fieldset className={styles.fieldset}>
                <legend className={look.srOnly}>{title}</legend>
                <div className={styles.stack}>{shown.map(control)}</div>
              </fieldset>
            </Disclose>
          );
        })}
      </div>
      {words !== '' && shownCount === 0 ? <p className={styles.muted}>No setting here matches what you typed.</p> : null}

      {clinicalChanged > 0 ? (
        <p role="status" className={mine.notice}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M12 3l10 18H2z" />
            <path d="M12 10v5M12 18h.01" />
          </svg>
          <span>
            <b>{clinicalChanged === 1 ? 'This changes a clinical setting.' : 'This changes clinical settings.'}</b> It needs 2 approvals from people other than you before it takes effect.
          </span>
        </p>
      ) : null}
      {failure !== null ? (
        <div role="alert" className={mine.problem}>
          <p className={styles.text}>{failure.words}</p>
          {failure.stale ? (
            <div className={mine.actions}>
              <Button variant="secondary" onClick={onReload}>
                Reload the settings
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className={mine.saveRow}>
        <p className={mine.saveHint}>
          {changedCount === 0
            ? 'Nothing changed yet.'
            : `${plural(changedCount, 'setting', 'settings')} changed. ${clinicalChanged > 0 ? 'It will be a draft until two other people approve.' : 'It needs one approval.'}`}
        </p>
        <Button variant="primary" type="submit" busy={busy} disabled={changedCount === 0} dataEl="ADMIN-DRAFT-SAVE-BTN">
          Save draft
        </Button>
      </div>
    </form>
  );
}

type ControlProps = {
  spec: SettingSpec;
  values: Readonly<Record<string, ConfigView['values'][string]>>;
  value: FieldValue;
  error: string | null;
  useDefault: boolean;
  onChange: (value: FieldValue) => void;
  onUseDefault: (on: boolean) => void;
};

function SettingControl({ spec, values, value, error, useDefault, onChange, onUseDefault }: ControlProps) {
  const label = labelFor(spec.key);
  const hint = hintFor(spec, values);
  const canReset = spec.key in values && spec.default !== null;
  const selectId = useId();
  const hintId = useId();
  let input;
  if (spec.kind === 'codes') {
    const chosen = Array.isArray(value) ? value : [];
    input = (
      <fieldset className={styles.fieldset} id={fieldId(spec.key)} disabled={useDefault}>
        <legend className={styles.legend}>{label}</legend>
        <p className={styles.muted}>{hint}</p>
        <div className={mine.chips}>
          {(spec.allowed ?? []).map((code) => {
            const on = chosen.includes(code);
            return (
              <button
                key={code}
                type="button"
                className={mine.chip}
                aria-pressed={on}
                onClick={() => onChange(on ? chosen.filter((c) => c !== code) : [...chosen, code])}
              >
                <span aria-hidden="true">{on ? '✓' : '+'}</span>
                {code}
              </button>
            );
          })}
        </div>
        {error !== null ? <p className={styles.problem}>{error}</p> : null}
      </fieldset>
    );
  } else if (spec.kind === 'int' && spec.choices !== null) {
    input = (
      <div className={styles.selectLabel}>
        <label htmlFor={selectId}>{label}</label>
        <p id={hintId} className={styles.muted}>
          {hint}
        </p>
        <select id={selectId} className={styles.select} value={String(value)} disabled={useDefault} aria-describedby={hintId} onChange={(event) => onChange(event.target.value)}>
          {spec.choices.map((choice) => (
            <option key={choice} value={String(choice)}>
              {String(choice)}
            </option>
          ))}
        </select>
      </div>
    );
  } else if (spec.kind === 'bool') {
    input = (
      <label className={styles.check}>
        <input type="checkbox" checked={value === true} disabled={useDefault} onChange={(event) => onChange(event.target.checked)} />
        <span>{label}</span>
      </label>
    );
  } else {
    input = (
      <TextField
        id={fieldId(spec.key)}
        label={label}
        value={typeof value === 'string' ? value : ''}
        onChange={onChange}
        requirement="none"
        hint={hint}
        error={error}
        type={spec.kind === 'int' ? 'number' : 'text'}
        inputMode={spec.kind === 'int' ? 'numeric' : 'text'}
        readOnly={useDefault}
      />
    );
  }
  return (
    <div className={styles.stack}>
      {input}
      {canReset ? (
        <label className={styles.check}>
          <input type="checkbox" checked={useDefault} aria-label={`Use the default for ${label}`} onChange={(event) => onUseDefault(event.target.checked)} />
          <span>Use the default</span>
        </label>
      ) : null}
    </div>
  );
}
