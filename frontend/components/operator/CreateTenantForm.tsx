'use client';

import { useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { operatorSend } from '@/lib/operator/browser';
import type { OdsRecord, OdsSearchHit } from '@/lib/operator/ods';
import { NHS_ORGANISATION_TYPE_CODES, ORGANISATION_TYPE_WORDS, organisationTypeWord, TENANT_ID_PATTERN } from '@/lib/operator/words';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { MAPPABLE_ROLE_WORDS } from '@/lib/tenantAdmin/roles';
import styles from '@/components/admin/admin.module.css';

// Creating a tenant (TEN-083): the operator names it and gives its id. The id is the path of the call, never a
// field of its body. Sending the same again finishes a creation that stopped. `recorded: false` means the
// tenant was created and the platform chain could not record it: the form says so and is not shown again.
//
// The form has three parts (design canvas "Overwatch admin portals", artboard 2): the organisation, the Entra
// directory its staff sign in through, and which directory group gives which role. The directory is saved as
// waiting: it is verified afterwards, on the tenant's page, once the domain is checked. A group is never given
// the administrator's role (the list has none): the first administrator is invited by text.

type Created = { created: boolean; recorded: boolean };
type Row = { key: number; group: string; role: string };

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// A tenant id suggested from a name: lower case, letters, digits and hyphens. The operator may change it before creating.
function suggestedTenantId(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 31).replace(/-+$/, '');
}

export function CreateTenantForm() {
  const [id, setId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [legalName, setLegalName] = useState('');
  const [type, setType] = useState<string>(ORGANISATION_TYPE_WORDS[0]![0]);
  const [ods, setOds] = useState('');
  const [country, setCountry] = useState('GB');
  const [zone, setZone] = useState('Europe/London');
  const [directory, setDirectory] = useState('');
  const [domain, setDomain] = useState('');
  const [odsName, setOdsName] = useState('');
  const [odsHits, setOdsHits] = useState<OdsSearchHit[] | null>(null);
  const [odsRecord, setOdsRecord] = useState<OdsRecord | null>(null);
  const [odsNote, setOdsNote] = useState('');
  const [lookupNote, setLookupNote] = useState('');
  /** The domain a directory id was found for (the card replaces the fields while it is set). */
  const [directoryFrom, setDirectoryFrom] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [nextKey, setNextKey] = useState(1);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [failure, setFailure] = useState('');
  const [done, setDone] = useState<(Created & { id: string; directory: boolean; groups: number }) | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();
  const edit = (set: (v: string) => void) => (v: string) => {
    submitKey.fresh();
    set(v);
  };
  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message ?? null;
  const editRow = (key: number, change: Partial<Row>) => {
    submitKey.fresh();
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...change } : r)));
  };
  const addRow = () => {
    submitKey.fresh();
    setRows((all) => [...all, { key: nextKey, group: '', role: MAPPABLE_ROLE_WORDS[0]![0] }]);
    setNextKey(nextKey + 1);
  };
  const removeRow = (key: number) => {
    submitKey.fresh();
    setRows((all) => all.filter((r) => r.key !== key));
  };

  // Searches the NHS directory by friendly name (a contains-match on the active organisations).
  async function searchNhs() {
    setOdsNote('');
    setOdsHits(null);
    const response = await fetch(`/api/bff/platform/ods?name=${encodeURIComponent(odsName.trim())}`, { cache: 'no-store' });
    const body = (await response.json()) as { results?: OdsSearchHit[]; message?: string };
    if (!response.ok || body.results === undefined) {
      setOdsNote(body.message ?? 'The NHS directory cannot be reached. Try again.');
      return;
    }
    setOdsHits(body.results);
    if (body.results.length === 0) setOdsNote('No active NHS organisation has that name. Try the start of its name, or enter it by hand below.');
  }

  // Takes one NHS organisation from the directory and fills the organisation from its record: the names, the ODS code,
  // the type its primary role suggests, and the country and time zone the NHS uses. The operator still checks each field.
  async function chooseNhs(code: string) {
    setOdsNote('');
    const response = await fetch(`/api/bff/platform/ods/${encodeURIComponent(code)}`, { cache: 'no-store' });
    const body = (await response.json()) as { record?: OdsRecord; message?: string };
    if (!response.ok || body.record === undefined) {
      setOdsNote(body.message ?? 'That organisation could not be read. Try again.');
      return;
    }
    const record = body.record;
    setOdsRecord(record);
    setOdsHits(null);
    setDisplayName(record.name);
    setLegalName(record.name);
    setOds(record.code);
    if (record.suggestedOrganisationType !== null) setType(record.suggestedOrganisationType);
    setCountry('GB');
    setZone('Europe/London');
    if (id.trim() === '') setId(suggestedTenantId(record.name));
  }

  function forgetDirectory() {
    setDirectoryFrom(null);
    setDirectory('');
    setLookupNote('');
  }

  function forgetNhs() {
    setOdsRecord(null);
    setOdsHits(null);
    setOdsNote('');
  }

  // Suggests the directory id from the organisation's domain (the public OpenID configuration, through this app's
  // route). It fills the field for the operator to check; nothing is saved here.
  async function lookUp() {
    setLookupNote('');
    const response = await fetch(`/api/bff/platform/directory-lookup?domain=${encodeURIComponent(domain.trim())}`, { cache: 'no-store' });
    if (!response.ok) {
      setLookupNote('Enter a domain name, for example example.nhs.uk.');
      return;
    }
    const found = (await response.json()) as { domain: string; directoryId: string | null };
    if (found.directoryId === null) {
      setLookupNote(`No directory was found for ${found.domain}. Ask the organisation for its Entra tenant id.`);
      return;
    }
    setDirectory(found.directoryId);
    setDirectoryFrom(found.domain);
    setLookupNote(`Found the directory for ${found.domain}. Check it is the organisation’s before you create the tenant.`);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure('');
    const problems: FieldError[] = [];
    if (NHS_ORGANISATION_TYPE_CODES.includes(type) && ods.trim() === '') problems.push({ field: 'ods-code', message: 'An NHS trust, ICB or GP practice needs its ODS code. Search for it above.' });
    if (!TENANT_ID_PATTERN.test(id) || id.startsWith('net-')) problems.push({ field: 'tenant-id', message: 'Use 2 to 31 lower-case letters, digits or hyphens, starting with a letter or a digit.' });
    if (displayName.trim() === '') problems.push({ field: 'display-name', message: 'Enter the name people know the organisation by.' });
    if (legalName.trim() === '') problems.push({ field: 'legal-name', message: 'Enter the organisation’s legal name.' });
    if (!/^[A-Za-z]{2}$/.test(country.trim())) problems.push({ field: 'country', message: 'Enter the two-letter country code.' });
    if (directory.trim() !== '' && !GUID.test(directory.trim())) problems.push({ field: 'directory-id', message: 'Directory id: enter it as a directory id, for example 00000000-0000-0000-0000-000000000000.' });
    rows.forEach((r, i) => {
      if (!GUID.test(r.group.trim())) problems.push({ field: `group-${r.key}`, message: `Group ${i + 1}: enter the group object id, for example 11111111-1111-4111-8111-111111111111.` });
    });
    setErrors(problems);
    if (problems.length > 0) return;
    const body: Record<string, unknown> = { displayName: displayName.trim(), legalName: legalName.trim(), organisationType: type, countryCode: country.trim().toUpperCase(), timeZone: zone.trim() };
    if (ods.trim() !== '') body.odsCode = ods.trim();
    // The NHS record the operator confirmed, only while the ODS code is still the one it was read under (DEC-1314).
    if (odsRecord !== null && ods.trim().toUpperCase() === odsRecord.code) body.odsRecord = odsRecord;
    if (directory.trim() !== '') body.directoryId = directory.trim().toLowerCase();
    if (rows.length > 0) body.roleMappings = rows.map((r) => ({ groupObjectId: r.group.trim().toLowerCase(), role: r.role }));
    setBusy(true);
    const result = await operatorSend<Created>('PUT', `/api/bff/platform/tenants/${id}`, body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setDone({ ...result.data, id, directory: directory.trim() !== '', groups: rows.length });
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
          {done.directory ? <p className={styles.text}>The directory is waiting to be verified. Check the domain, then verify it on the tenant’s page.</p> : null}
          {done.groups > 0 ? <p className={styles.text}>{done.groups === 1 ? '1 group is mapped to a role.' : `${done.groups} groups are mapped to roles.`}</p> : null}
          <p className={styles.text}>
            <a className={styles.link} href={`/operator/tenants/${done.id}`}>
              Open the tenant
            </a>
          </p>
        </div>
      ) : null}
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Create a tenant">
        <ErrorSummary errors={errors} />
        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>1 The organisation</legend>
          {odsRecord === null ? (
            <>
              <TextField id="ods-name" label="Organisation’s name" value={odsName} onChange={edit(setOdsName)} requirement="none" hint="The name people know it by, for example Ardleigh Surgery. For an NHS organisation this finds its ODS code and fills the rest." autoComplete="off" dataEl="OP-CREATE-ODS-NAME-INPUT" />
              <p className={styles.row}>
                <Button variant="secondary" onClick={() => void searchNhs()} dataEl="OP-CREATE-ODS-SEARCH-BTN">
                  Search the NHS directory
                </Button>
              </p>
              {odsNote !== '' ? <p className={styles.text} role="status">{odsNote}</p> : null}
              {odsHits !== null && odsHits.length > 0 ? (
                <ul className={styles.stack}>
                  {odsHits.map((hit) => (
                    <li key={hit.code}>
                      <Button variant="neutral" onClick={() => void chooseNhs(hit.code)} dataEl="OP-CREATE-ODS-PICK-BTN">
                        {`Use ${hit.name} (${hit.code}${hit.postcode !== null ? `, ${hit.postcode}` : ''})`}
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <div className={styles.panel} data-el="OP-CREATE-ODS-RECORD">
              <p className={styles.text}>
                <strong>{odsRecord.name}</strong> · {odsRecord.code} · {odsRecord.status}
                {odsRecord.postcode !== null ? ` · ${odsRecord.postcode}` : ''}
              </p>
              <p className={styles.text}>
                Roles: {odsRecord.roles.map((r) => `${r.name}${r.primary ? ' (primary)' : ''}`).join(', ') || 'none'}
              </p>
              <p className={styles.text}>
                Active links: {odsRecord.links.map((l) => `${l.name} (${l.code})`).join(', ') || 'none'}
              </p>
              {odsRecord.lastChangedAt !== null ? <p className={styles.text}>Last changed in the NHS directory: {odsRecord.lastChangedAt}</p> : null}
              <p className={styles.text}>The fields below are filled from this record. Check them before you create the tenant.</p>
              {odsRecord.suggestedOrganisationType === null ? (
                <p className={styles.text}>The NHS directory does not give this organisation an NHS type. Choose its organisation type below.</p>
              ) : null}
              <Button variant="neutral" onClick={forgetNhs} dataEl="OP-CREATE-ODS-FORGET-BTN">
                Choose another organisation
              </Button>
            </div>
          )}
          {odsRecord === null ? (
            <p className={styles.text}>Not an NHS organisation? Enter it by hand below. An NHS trust, ICB or GP practice needs its ODS code.</p>
          ) : null}
          <TextField id="tenant-id" label="Tenant id" value={id} onChange={edit(setId)} requirement="none" hint="Lower-case letters, digits and hyphens. It cannot be changed." error={problemOf('tenant-id')} autoComplete="off" />
          {odsRecord === null ? (
            <>
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
          <TextField id="ods-code" label="ODS code" value={ods} onChange={edit(setOds)} requirement="optional" error={problemOf('ods-code')} />
          <TextField id="country" label="Country code" value={country} onChange={edit(setCountry)} requirement="none" error={problemOf('country')} />
          <TextField id="time-zone" label="Time zone" value={zone} onChange={edit(setZone)} requirement="none" />
            </>
          ) : (
            <p className={styles.text}>Organisation type: {organisationTypeWord(type)} · Country: {country} · Time zone: {zone}</p>
          )}
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>2 Entra directory</legend>
          <p className={styles.text}>
            The directory the organisation’s staff sign in with. It is saved as <strong>waiting</strong>: nobody can use it until you have checked the domain and verified it, on the tenant’s page.
          </p>
          {directoryFrom === null ? (
            <>
          <TextField
            id="directory-domain"
            label="Organisation’s domain"
            value={domain}
            onChange={edit(setDomain)}
            requirement="optional"
            hint="Look up the directory id from it, then check it."
            autoComplete="off"
            dataEl="OP-CREATE-DOMAIN-INPUT"
          />
          <p className={styles.row}>
            <Button variant="secondary" onClick={() => void lookUp()} dataEl="OP-CREATE-DOMAIN-LOOKUP-BTN">
              Look up directory id
            </Button>
          </p>
          {lookupNote !== '' ? <p className={styles.text} role="status">{lookupNote}</p> : null}
          <TextField
            id="directory-id"
            label="Directory id"
            value={directory}
            onChange={edit(setDirectory)}
            requirement="optional"
            hint="As shown in the organisation’s Entra tenant properties. Its administrator can also bind it later."
            error={problemOf('directory-id')}
            autoComplete="off"
            dataEl="OP-CREATE-DIRECTORY-INPUT"
          />
            </>
          ) : (
            <div className={styles.panel} data-el="OP-CREATE-DIRECTORY-CARD">
              <p className={styles.text}>
                <strong>Entra directory</strong> · {directory}
              </p>
              <p className={styles.text}>Found from the domain {directoryFrom}. Check it is the organisation’s before you create the tenant.</p>
              <Button variant="neutral" onClick={forgetDirectory} dataEl="OP-CREATE-DIRECTORY-FORGET-BTN">
                Choose another directory
              </Button>
            </div>
          )}
          <p className={styles.row}>
            <span className={styles.text}>Verification</span>
            <span className={`${styles.tag} ${styles.tagDashed}`}>Waiting: verified after creation</span>
          </p>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>3 Who gets which role</legend>
          <p className={styles.text}>
            Map a directory group to a staff role. Someone in the group gets that role when they sign in. A group cannot be given the administrator’s role: the first administrator is invited by text.
          </p>
          {rows.length === 0 ? <p className={styles.muted}>No group is mapped yet. You can add them now, or the organisation’s administrator can later.</p> : null}
          {rows.map((r, i) => (
            <div key={r.key} className={styles.mappingRow} role="group" aria-label={`Group ${i + 1}`}>
              <TextField id={`group-${r.key}`} label="Group object id" value={r.group} onChange={(v) => editRow(r.key, { group: v })} requirement="none" error={problemOf(`group-${r.key}`)} autoComplete="off" />
              <div className={styles.selectLabel}>
                <label htmlFor={`role-${r.key}`}>Role</label>
                <select id={`role-${r.key}`} className={styles.select} value={r.role} onChange={(e) => editRow(r.key, { role: e.target.value })}>
                  {MAPPABLE_ROLE_WORDS.map(([code, word]) => (
                    <option key={code} value={code}>
                      {word}
                    </option>
                  ))}
                </select>
              </div>
              <Button variant="neutral" onClick={() => removeRow(r.key)} dataEl="OP-CREATE-GROUP-REMOVE-BTN">
                Remove<span className={styles.srOnly}>{` group ${i + 1}`}</span>
              </Button>
            </div>
          ))}
          <div className={styles.actions}>
            <Button variant="secondary" onClick={addRow} dataEl="OP-CREATE-GROUP-ADD-BTN">
              {rows.length === 0 ? 'Add a group' : 'Add another group'}
            </Button>
          </div>
        </fieldset>
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
