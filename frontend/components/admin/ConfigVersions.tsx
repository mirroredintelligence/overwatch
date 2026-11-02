'use client';

import { useId, useMemo, useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import { buildDraft, effective, fieldId, hintFor, isChanged, labelFor, toField, type FieldValue } from '@/lib/tenantAdmin/draft';
import type { ConfigView, SettingSpec } from '@/lib/tenantAdmin/views';
import { Disclose } from './Disclose';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';
import look from './Disclose.module.css';

// The settings page (TEN-076): the versions of the organisation's settings, which is in force, and a change
// drafted from it. A change is a new version. A clinical one needs two people who are not its author to
// approve it, and the page says so before anything is drafted. The draft is made from the version this page
// read (`basedOn`): a stale one is the back end's 409, and nothing here overwrites a newer version.

export const STATUS_WORD: Record<ConfigView['status'], string> = {
  draft: 'Draft',
  'pending-approval': 'Waiting for approval',
  current: 'In force',
  superseded: 'Replaced',
};

export function ConfigVersions() {
  const versions = useAdminRead<{ versions: ConfigView[] }>('/api/bff/tenant/config/versions');
  const settings = useAdminRead<{ settings: SettingSpec[] }>('/api/bff/tenant/settings');
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<{ version: number; required: number } | null>(null);

  if (versions.state.status === 'loading' || settings.state.status === 'loading') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Settings</h1>
        <Loading label="Loading the settings."><SkeletonRows count={3} /></Loading>
      </main>
    );
  }
  if (versions.state.status === 'failed' || settings.state.status === 'failed') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Settings</h1>
        <p role="alert" className={styles.problem}>
          We could not load the settings.
        </p>
      </main>
    );
  }
  const list = versions.state.data.versions;
  const inForce = list.find((v) => v.status === 'current') ?? null;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Settings</h1>
      <p className={styles.lede}>
        Settings change as a new version. A change to a clinical setting needs two people to approve it. The person who wrote it cannot be one of them.
      </p>

      {saved !== null ? (
        <div role="status" className={styles.panel}>
          <p className={styles.ok}>
            {`Draft version ${saved.version} saved. It needs ${saved.required === 1 ? '1 approval' : `${saved.required} approvals from people other than you`}.`}
          </p>
          <p className={styles.text}>
            <a className={styles.link} href={`/admin/config/${saved.version}`}>
              {`Open version ${saved.version}`}
            </a>
          </p>
        </div>
      ) : null}

      {list.length === 0 ? (
        <p className={styles.text}>No version of the settings has been made yet.</p>
      ) : (
        <div className={look.inner}>
          <ol className={look.timeline} aria-label="Configuration versions">
            {list.map((v) => (
              <li key={v.version} className={v.status === 'current' ? `${look.stop} ${look.stopNow}` : look.stop} style={{ animationDelay: `${Math.min(list.indexOf(v), 8) * 35}ms` }}>
                <a className={look.stopLink} href={`/admin/config/${v.version}`} aria-label={`Version ${v.version}`}>
                  {`Version ${v.version}`}
                </a>
                <span className={`${look.stopStatus} ${v.status === 'current' ? `${look.tag} ${look.tagOn}` : `${look.tag} ${look.tagDashed}`}`}>{STATUS_WORD[v.status]}</span>
                <span className={look.stopMeta}>{`${v.approvals} of ${v.approvalsRequired}`}</span>
                <span className={`${look.stopKind} ${v.clinicalKeys.length > 0 ? `${look.tag} ${look.tagClinical}` : `${look.tag} ${look.tagDashed}`}`}>{v.clinicalKeys.length > 0 ? 'Clinical' : 'Operational'}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {open ? (
        <DraftForm
          key={inForce?.version ?? 0}
          specs={settings.state.data.settings}
          values={inForce?.values ?? {}}
          basedOn={inForce?.version ?? 0}
          onCancel={() => setOpen(false)}
          onSaved={(result) => {
            setSaved(result);
            setOpen(false);
            versions.reload();
          }}
        />
      ) : (
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => setOpen(true)} dataEl="ADMIN-DRAFT-BTN">
            Draft a change
          </Button>
        </div>
      )}
    </main>
  );
}

type FormProps = {
  specs: SettingSpec[];
  values: Readonly<Record<string, ConfigView['values'][string]>>;
  basedOn: number;
  onCancel: () => void;
  onSaved: (result: { version: number; required: number }) => void;
};

function DraftForm({ specs, values, basedOn, onCancel, onSaved }: FormProps) {
  const initial = useMemo(() => Object.fromEntries(specs.map((s) => [s.key, toField(s, effective(s, values))])) as Record<string, FieldValue>, [specs, values]);
  const [fields, setFields] = useState<Record<string, FieldValue>>(initial);
  const [useDefault, setUseDefault] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [failure, setFailure] = useState('');
  const [busy, setBusy] = useState(false);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const submitKey = useSubmitKey();

  function edit(key: string, value: FieldValue) {
    submitKey.fresh();
    setFields((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure('');
    const draft = buildDraft(specs, values, fields, useDefault);
    if (draft.problems.length > 0) {
      setErrors(draft.problems.map((p) => ({ field: fieldId(p.key), message: p.message })));
      // The first problem is in a group that may be shut: open it, so the person sees what to fix.
      const first = specs.find((spec) => spec.key === draft.problems[0]!.key);
      if (first !== undefined) setOpenGroup(first.safetyClass);
      return;
    }
    setErrors([]);
    if (Object.keys(draft.changes).length === 0 && draft.removals.length === 0) {
      setFailure('You have not changed anything.');
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
        ? 'The settings changed while you were working. Reload the page and try again.'
        : 'The draft could not be saved. Try again.',
    );
  }

  const problemOf = (key: string) => errors.find((e) => e.field === fieldId(key))?.message ?? null;
  const words = filter.trim().toLowerCase();
  const matches = (spec: SettingSpec) => words === '' || labelFor(spec.key).toLowerCase().includes(words) || spec.key.toLowerCase().includes(words);
  // A setting is changed when the person has altered it from what is in force, or asked for its default.
  const changed = (spec: SettingSpec) => useDefault.has(spec.key) || isChanged(spec, toField(spec, effective(spec, values)), fields[spec.key] ?? '');
  const clinicalChanged = specs.filter((spec) => spec.safetyClass === 'clinical' && changed(spec));

  const control = (spec: SettingSpec) => (
    <div key={spec.key} className={look.setting} data-changed={changed(spec)}>
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

  const groups: [string, string, SettingSpec[]][] = [
    ['clinical', 'Clinical settings', specs.filter((s) => s.safetyClass === 'clinical')],
    ['operational', 'Operational settings', specs.filter((s) => s.safetyClass === 'operational')],
  ];
  const anyMatch = groups.some(([, , list]) => list.some(matches));

  return (
    <form className={`${styles.stack} ${look.arrive}`} onSubmit={submit} noValidate aria-label="Draft a change">
      <ErrorSummary errors={errors} />
      <div className={look.find}>
        <label htmlFor="find-setting" className={look.findLabel}>
          Find a setting
        </label>
        <input
          id="find-setting"
          className={look.findInput}
          type="search"
          autoComplete="off"
          placeholder="Type part of a name, such as pressure"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <div className={look.list}>
        {groups.map(([id, name, list]) => {
          const shown = list.filter(matches);
          const count = list.filter(changed).length;
          if (words !== '' && shown.length === 0) return null;
          return (
            <Disclose
              key={id}
              open={words !== '' ? true : openGroup === id}
              onToggle={() => setOpenGroup((now) => (now === id ? null : id))}
              tone={id === 'clinical' ? 'clinical' : undefined}
              title={name}
              hint={id === 'clinical' ? 'A change to any of these needs two approvals from people other than its author.' : `${shown.length} ${shown.length === 1 ? 'setting' : 'settings'}`}
              aside={count > 0 ? <span className={look.badge}>{`${count} changed`}</span> : <span>{shown.length}</span>}
            >
              <fieldset className={styles.fieldset}>
                <legend className={look.srOnly}>{name}</legend>
                <div className={look.inner}>{shown.map(control)}</div>
              </fieldset>
            </Disclose>
          );
        })}
      </div>
      {words !== '' && !anyMatch ? <p className={look.muted}>No setting matches that. Try fewer letters.</p> : null}
      {clinicalChanged.length > 0 ? (
        <p className={look.notice} aria-live="polite">
          {`This changes ${clinicalChanged.length === 1 ? 'a clinical setting' : 'clinical settings'} (${clinicalChanged.map((spec) => labelFor(spec.key)).join(', ')}), so it needs two approvals from people other than you.`}
        </p>
      ) : null}
      {failure !== '' ? (
        <p role="alert" className={styles.problem}>
          {failure}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-DRAFT-SAVE-BTN">
          Save draft
        </Button>
        <Button variant="neutral" onClick={onCancel}>
          Cancel
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
        {(spec.allowed ?? []).map((code) => (
          <label key={code} className={styles.check}>
            <input
              type="checkbox"
              checked={chosen.includes(code)}
              onChange={(event) => onChange(event.target.checked ? [...chosen, code] : chosen.filter((c) => c !== code))}
            />
            <span>{code}</span>
          </label>
        ))}
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
