'use client';

import { useState } from 'react';
import { leadPost } from '@/lib/lead/browser';
import { districtCheckFrom, typedDistricts, type DistrictCheck } from '@/lib/lead/postcodeDistricts';
import styles from './DistrictCheck.module.css';

// The two steps of a service's postcode districts (DEC-1329). Check: each district typed is verified and
// its postcode count shown, so the lead can narrow it (type a longer start such as "DT4 0") before anything
// is queued. Confirm: a checked district is queued for a background download, and the request returns at
// once; the page never waits for the postcodes.

type Row =
  | { state: 'checking'; prefix: string }
  | { state: 'found'; check: DistrictCheck }
  | { state: 'missing'; prefix: string }
  | { state: 'unavailable'; prefix: string }
  | { state: 'queuing'; check: DistrictCheck }
  | { state: 'queued'; check: DistrictCheck }
  | { state: 'queue-failed'; check: DistrictCheck };

export function DistrictCheckPanel({ text }: { text: string }) {
  const [rows, setRows] = useState<Row[]>([]);

  async function checkAll() {
    const typed = typedDistricts(text);
    setRows(typed.map((prefix) => ({ state: 'checking', prefix })));
    const next = await Promise.all(typed.map((prefix) => checkOne(prefix)));
    setRows(next);
  }

  function replaceRow(prefix: string, row: Row) {
    setRows((current) => current.map((item) => (rowPrefix(item) === prefix ? row : item)));
  }

  async function confirm(check: DistrictCheck) {
    replaceRow(check.prefix, { state: 'queuing', check });
    const result = await leadPost(`/api/bff/postcode-districts/download?text=${encodeURIComponent(check.prefix)}`, {});
    replaceRow(check.prefix, result.ok ? { state: 'queued', check } : { state: 'queue-failed', check });
  }

  return (
    <div className={styles.panel}>
      <button type="button" className={styles.check} onClick={checkAll} disabled={typedDistricts(text).length === 0}>
        Check districts
      </button>
      <p className={styles.hint}>
        Too many postcodes? Type a longer start, such as DT4 0, and check again.
      </p>
      {rows.length > 0 ? (
        <ul className={styles.rows} aria-label="District checks">
          {rows.map((row) => (
            <li key={rowPrefix(row)} className={styles.row}>
              <RowText row={row} />
              {row.state === 'found' ? (
                <button type="button" className={styles.confirm} onClick={() => confirm(row.check)}>
                  Confirm {row.check.prefix}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function RowText({ row }: { row: Row }) {
  switch (row.state) {
    case 'checking':
      return <span>{row.prefix}: checking…</span>;
    case 'found':
      return <span>{row.check.prefix}: {row.check.postcodes.toLocaleString('en-GB')} postcodes</span>;
    case 'missing':
      return <span>{row.prefix}: not a district with postcodes</span>;
    case 'unavailable':
      return <span>{row.prefix}: could not be checked, try again</span>;
    case 'queuing':
      return <span>{row.check.prefix}: queuing…</span>;
    case 'queued':
      return (
        <span>
          {row.check.prefix}: queued. The postcodes download in the background, about {row.check.postcodes.toLocaleString('en-GB')} postcodes.
        </span>
      );
    case 'queue-failed':
      return <span>{row.check.prefix}: could not be queued, try again</span>;
  }
}

function rowPrefix(row: Row): string {
  return 'prefix' in row ? row.prefix : row.check.prefix;
}

async function checkOne(prefix: string): Promise<Row> {
  let response: Response;
  try {
    response = await fetch(`/api/bff/postcode-districts/check?text=${encodeURIComponent(prefix)}`, {
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch {
    return { state: 'unavailable', prefix };
  }
  if (response.status === 404 || response.status === 422 || response.status === 400) {
    return { state: 'missing', prefix };
  }
  if (!response.ok) return { state: 'unavailable', prefix };
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    return { state: 'unavailable', prefix };
  }
  const check = districtCheckFrom(data);
  return check === null ? { state: 'unavailable', prefix } : { state: 'found', check };
}
