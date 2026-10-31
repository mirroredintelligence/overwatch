'use client';

import { useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { operatorSend } from '@/lib/operator/browser';
import { ORGANISATION_TYPE_WORDS, TENANT_ID_PATTERN } from '@/lib/operator/words';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import styles from '@/components/admin/admin.module.css';

// Creating a tenant (TEN-083): the operator names it and gives its id. The id is the path of the call, never a
// field of its body. Sending the same again finishes a creation that stopped. `recorded: false` means the
// tenant was created and the platform chain could not record it: the form says so and is not shown again.

type Created = { created: boolean; recorded: boolean };

export function CreateTenantForm() {
  const [id, setId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [legalName, setLegalName] = useState('');
  const [type, setType] = useState<string>(ORGANISATION_TYPE_WORDS[0]![0]);
  const [ods, setOds] = useState('');
  const [country, setCountry] = useState('GB');
  const [zone, setZone] = useState('Europe/London');
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [failure, setFailure] = useState('');
  const [done, setDone] = useState<(Created & { id: string }) | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();
  const edit = (set: (v: string) => void) => (v: string) => {
    submitKey.fresh();
    set(v);
  };
  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message ?? null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure('');
    const problems: FieldError[] = [];
    if (!TENANT_ID_PATTERN.test(id) || id.startsWith('net-')) problems.push({ field: 'tenant-id', message: 'Use 2 to 31 lower-case letters, digits or hyphens, starting with a letter or a digit.' });
    if (displayName.trim() === '') problems.push({ field: 'display-name', message: 'Enter the name people know the organisation by.' });
    if (legalName.trim() === '') problems.push({ field: 'legal-name', message: 'Enter the organisation’s legal name.' });
    if (!/^[A-Za-z]{2}$/.test(country.trim())) problems.push({ field: 'country', message: 'Enter the two-letter country code.' });
    setErrors(problems);
    if (problems.length > 0) return;
    const body: Record<string, string> = { displayName: displayName.trim(), legalName: legalName.trim(), organisationType: type, countryCode: country.trim().toUpperCase(), timeZone: zone.trim() };
    if (ods.trim() !== '') body.odsCode = ods.trim();
    setBusy(true);
    const result = await operatorSend<Created>('PUT', `/api/bff/platform/tenants/${id}`, body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setDone({ ...result.data, id });
      return;
    }
    setFailure(
      result.status === 409
        ? 'That id cannot be used. It may be taken, or the tenant is past the point where it can be created again.'
        : 'The tenant could not be created. Try again.',
    );
  }

  if (done !== null && !done.recorded) {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Create a tenant</h1>
        <p role="alert" className={styles.problem}>
          The tenant was created, but the platform record could not be written. Do not create it again. Tell the person who looks after the platform record.
        </p>
        <p className={styles.text}>
          <a className={styles.link} href={`/operator/tenants/${done.id}`}>
            Open the tenant
          </a>
        </p>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Create a tenant</h1>
      <p className={styles.lede}>A tenant is one organisation. It starts being set up and does nothing until it is activated.</p>
      {done !== null ? (
        <div role="status" className={styles.panel}>
          <p className={styles.ok}>{done.created ? 'Tenant created. It is being set up.' : 'The creation had stopped before. It is finished now.'}</p>
          <p className={styles.text}>
            <a className={styles.link} href={`/operator/tenants/${done.id}`}>
              Open the tenant
            </a>
          </p>
        </div>
      ) : null}
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Create a tenant">
        <ErrorSummary errors={errors} />
        <TextField id="tenant-id" label="Tenant id" value={id} onChange={edit(setId)} requirement="none" hint="Lower-case letters, digits and hyphens. It cannot be changed." error={problemOf('tenant-id')} autoComplete="off" />
        <TextField id="display-name" label="Display name" value={displayName} onChange={edit(setDisplayName)} requirement="none" error={problemOf('display-name')} />
        <TextField id="legal-name" label="Legal name" value={legalName} onChange={edit(setLegalName)} requirement="none" error={problemOf('legal-name')} />
        <div className={styles.selectLabel}>
          <label htmlFor="organisation-type">Organisation type</label>
          <select id="organisation-type" className={styles.select} value={type} onChange={(e) => edit(setType)(e.target.value)}>
            {ORGANISATION_TYPE_WORDS.map(([code, word]) => (
              <option key={code} value={code}>
                {word}
              </option>
            ))}
          </select>
        </div>
        <TextField id="ods-code" label="ODS code" value={ods} onChange={edit(setOds)} requirement="optional" />
        <TextField id="country" label="Country code" value={country} onChange={edit(setCountry)} requirement="none" error={problemOf('country')} />
        <TextField id="time-zone" label="Time zone" value={zone} onChange={edit(setZone)} requirement="none" />
        {failure !== '' ? (
          <p role="alert" className={styles.problem}>
            {failure}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="OP-CREATE-SUBMIT-BTN">
            Create tenant
          </Button>
        </div>
      </form>
    </main>
  );
}
