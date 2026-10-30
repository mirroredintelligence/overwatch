'use client';

import { useEffect, useState } from 'react';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost, leadRead } from '@/lib/lead/browser';
import type { FlagItem } from '@/lib/lead/flags';
import styles from './Lead.module.css';

// Reports to check (W42): the flags the rules raised on open reports. "To check" lists the open flags; the
// "Checked" list is not on the back end yet, so its tab answers that the list could not be loaded.
// Accepting a figure or marking it checked takes the flag out of "To check". A suspension is made on its own
// page, from the link.

type Tab = 'to-check' | 'checked';

const FOOTNOTE =
  'Flagged by rules: out-of-range twice, many changes in a short time, or a figure that differs from what advisors recorded by phone.';

/** The BFF's answer: `{counts, items}`. A shape that is not that is an empty list plus a failure, never a guess. */
function flagsFromAnswer(body: unknown): FlagItem[] {
  const list = (body as { items?: unknown } | undefined)?.items;
  if (!Array.isArray(list)) throw new Error('not the flags answer');
  return list.filter(
    (item): item is FlagItem =>
      typeof item?.id === 'string' &&
      typeof item.serviceId === 'string' &&
      typeof item.serviceName === 'string' &&
      typeof item.reason === 'string' &&
      typeof item.summary === 'string',
  );
}

export function ReportFlags() {
  const [tab, setTab] = useState<Tab>('to-check');
  const [items, setItems] = useState<FlagItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [phoned, setPhoned] = useState<FlagItem | null>(null);

  useEffect(() => {
    let cancelled = false;
    void leadRead(`/api/bff/lead/flags?state=${tab}`).then((result) => {
      if (cancelled) return;
      setLoading(false);
      if (!result.ok) {
        setItems([]);
        setFailed(result.status === 403 ? CANNOT_DO : 'We could not load these reports. Try again shortly.');
        return;
      }
      try {
        const flags = flagsFromAnswer(result.body);
        setFailed(null);
        setItems(flags);
      } catch {
        setItems([]);
        setFailed('We could not load these reports. Try again shortly.');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [tab]);

  async function resolve(item: FlagItem, action: 'accept' | 'checked') {
    setNotice('');
    const result = await leadPost(`/api/bff/lead/flags/${encodeURIComponent(item.id)}`, { action });
    if (!result.ok) {
      setNotice(result.status === 403 ? CANNOT_DO : 'The report could not be updated. Try again.');
      return;
    }
    setItems((current) => current.filter((flag) => flag.id !== item.id));
    setNotice('Moved to Checked.');
  }

  const count = items.length;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Reports to check</h1>

      <div role="tablist" aria-label="Reports" className={styles.tabs}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'to-check'}
          onClick={() => {
            setLoading(true);
            setTab('to-check');
          }}
          className={styles.tab}
        >
          {`To check (${loading ? '…' : count})`}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'checked'}
          onClick={() => {
            setLoading(true);
            setTab('checked');
          }}
          className={styles.tab}
        >
          Checked
        </button>
      </div>

      {failed !== null ? (
        <p role="alert" className={styles.fieldError}>
          {failed}
        </p>
      ) : null}

      {loading ? <p className={styles.muted}>Loading the reports to check.</p> : null}

      {!loading && failed === null && count === 0 ? <p className={styles.line}>No reports to check.</p> : null}

      <div className={styles.stack}>
        {!loading && failed === null
          ? items.map((item) => {
              const many = item.reason === 'many-changes';
              return (
                <section key={item.id} className={styles.card} aria-labelledby={`flag-${item.id}`}>
                  <h2 id={`flag-${item.id}`} className={styles.sectionHeading}>
                    {item.serviceName}
                  </h2>
                  <p className={styles.line}>{item.summary}</p>
                  <div className={styles.actions}>
                    <Button variant="secondary" onClick={() => setPhoned(item)} dataEl="LEAD-FLAG-PHONED-BTN">
                      Phone to confirm
                    </Button>
                    {many ? (
                      <Button variant="neutral" onClick={() => void resolve(item, 'checked')} dataEl="LEAD-FLAG-CHECKED-BTN">
                        Mark as checked
                      </Button>
                    ) : (
                      <>
                        <Button variant="primary" onClick={() => void resolve(item, 'accept')} dataEl="LEAD-FLAG-ACCEPT-BTN">
                          Accept the figure
                        </Button>
                        <Button variant="neutral" href={`/lead/services/${encodeURIComponent(item.serviceId)}/suspend`} dataEl="LEAD-FLAG-SUSPEND-LINK">
                          Suspend service
                        </Button>
                      </>
                    )}
                  </div>
                </section>
              );
            })
          : null}
      </div>

      <p role="status" className={styles.line}>
        {notice}
      </p>
      <p className={styles.muted}>{FOOTNOTE}</p>

      <LeadPhonedDialog
        open={phoned !== null}
        serviceId={phoned?.serviceId ?? ''}
        serviceName={phoned?.serviceName ?? ''}
        onClose={() => setPhoned(null)}
      />
    </main>
  );
}
