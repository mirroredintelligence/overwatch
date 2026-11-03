'use client';

import { type KeyboardEvent, useEffect, useRef, useState } from 'react';
import { FlagList } from './FlagList';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { CANNOT_DO, leadPost, leadRead } from '@/lib/lead/browser';
import type { FlagItem } from '@/lib/lead/flags';
import styles from './ReportFlags.module.css';

// Reports to check (W42, LDR-09): the flags the rules raised on open reports. A master list on the left and the
// open flag beside it, with the reason in words and the actions explained. "To check" lists the open flags; the
// "Checked" list is not on the back end yet, so its tab answers that the list could not be loaded.
// Accepting a figure or marking it checked takes the flag out of "To check". A suspension is made on its own
// page, from the link. On a phone the list is the page and a tap opens the flag as a step of its own, with
// "Phone to confirm" fixed at the bottom. The "last reports" strip is not drawn: the flag has no figures.

type Tab = 'to-check' | 'checked';
type Step = 'list' | 'detail';

const FOOTNOTE =
  'Flagged by rules: out-of-range twice, many changes in a short time, or a figure that differs from what advisors recorded by phone. Not a league table, and never used to assess advisors.';
const NOT_LOADED = 'We could not load these reports. Try again shortly.';
const TABS: readonly Tab[] = ['to-check', 'checked'];

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
  const [openId, setOpenId] = useState<string | null>(null);
  const [step, setStep] = useState<Step>('list');
  const [reads, setReads] = useState(0);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ 'to-check': null, checked: null });

  useEffect(() => {
    let cancelled = false;
    void leadRead(`/api/bff/lead/flags?state=${tab}`).then((result) => {
      if (cancelled) return;
      setLoading(false);
      if (!result.ok) {
        setItems([]);
        setFailed(result.status === 403 ? CANNOT_DO : NOT_LOADED);
        return;
      }
      try {
        const flags = flagsFromAnswer(result.body);
        setFailed(null);
        setItems(flags);
      } catch {
        setItems([]);
        setFailed(NOT_LOADED);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [tab, reads]);

  function choose(next: Tab) {
    if (next === tab) return;
    setLoading(true);
    setNotice('');
    setOpenId(null);
    setStep('list');
    setTab(next);
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const at = TABS.indexOf(tab);
    let to = -1;
    if (event.key === 'ArrowRight') to = (at + 1) % TABS.length;
    else if (event.key === 'ArrowLeft') to = (at + TABS.length - 1) % TABS.length;
    else if (event.key === 'Home') to = 0;
    else if (event.key === 'End') to = TABS.length - 1;
    if (to < 0) return;
    event.preventDefault();
    choose(TABS[to]);
    tabRefs.current[TABS[to]]?.focus();
  }

  function tryAgain() {
    setLoading(true);
    setFailed(null);
    setReads((n) => n + 1);
  }

  async function resolve(item: FlagItem, action: 'accept' | 'checked') {
    setNotice('');
    const result = await leadPost(`/api/bff/lead/flags/${encodeURIComponent(item.id)}`, { action });
    if (!result.ok) {
      setNotice(result.status === 403 ? CANNOT_DO : 'The report could not be updated. Try again.');
      return;
    }
    setItems((current) => current.filter((flag) => flag.id !== item.id));
    setOpenId(null);
    setStep('list');
    setNotice('Moved to Checked.');
  }

  const count = items.length;
  const current = items.find((item) => item.id === openId) ?? items[0] ?? null;
  const ready = !loading && failed === null;
  const open = tab === 'to-check';

  return (
    <main className={styles.page}>
      <PageHeader title="Reports to check" />

      <div role="tablist" aria-label="Reports" className={styles.tabs} onKeyDown={onTabKeyDown}>
        {TABS.map((id) => (
          <button
            key={id}
            ref={(node) => {
              tabRefs.current[id] = node;
            }}
            type="button"
            role="tab"
            id={`flags-tab-${id}`}
            aria-selected={tab === id}
            aria-controls="flags-panel"
            tabIndex={tab === id ? 0 : -1}
            onClick={() => choose(id)}
            className={styles.tab}
          >
            {id === 'checked' ? 'Checked' : tab === 'to-check' ? `To check (${loading ? '…' : count})` : 'To check'}
          </button>
        ))}
      </div>

      <div role="tabpanel" id="flags-panel" aria-labelledby={`flags-tab-${tab}`} className={styles.panel}>
        {failed !== null ? (
          <div role="alert" className={styles.failure}>
            <p className={styles.failureText}>{failed}</p>
            <Button variant="secondary" onClick={tryAgain} dataEl="LEAD-FLAG-RETRY-BTN">
              Try again
            </Button>
          </div>
        ) : null}

        {loading ? (
          <Loading label="Loading the reports to check.">
            <SkeletonRows count={3} />
          </Loading>
        ) : null}

        {ready && count === 0 ? (
          <p className={styles.empty}>{open ? 'No reports to check.' : 'No reports have been checked.'}</p>
        ) : null}

        {ready && current !== null ? (
          <div className={styles.stage} data-step={step} data-testid="flags-stage">
            <div className={styles.list}>
              <FlagList
                items={items}
                currentId={current.id}
                onOpen={(id) => {
                  setOpenId(id);
                  setStep('detail');
                }}
              />
            </div>

            <section key={current.id} className={styles.detail} aria-label={current.serviceName}>
              {step === 'detail' ? (
                <button type="button" className={styles.back} onClick={() => setStep('list')}>
                  <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
                    <path d="M12 5l-5 5 5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Back to the list
                </button>
              ) : null}
              <div>
                <div className={styles.kicker}>{open ? 'Report to check' : 'Checked report'}</div>
                <h2 className={styles.name}>{current.serviceName}</h2>
                <p className={styles.reason}>{current.summary}</p>
              </div>

              {open ? (
                <>
                  <div className={styles.explain}>
                    <div className={styles.act}>
                      <span className={styles.actName}>Phone to confirm</span>
                      <span className={styles.actText}>
                        Ring the service and record what they say. Their answer replaces the flagged figure.
                      </span>
                    </div>
                    <div className={styles.act}>
                      <span className={styles.actName}>{current.reason === 'many-changes' ? 'Mark as checked' : 'Accept the figure'}</span>
                      <span className={styles.actText}>
                        {current.reason === 'many-changes'
                          ? 'You looked and the changes were real. The flag moves to Checked.'
                          : 'You looked and the figure is right. The flag moves to Checked.'}
                      </span>
                    </div>
                  </div>

                  <div className={styles.actions}>
                    <div className={styles.primary}>
                      <Button variant="primary" onClick={() => setPhoned(current)} dataEl="LEAD-FLAG-PHONED-BTN">
                        Phone to confirm
                      </Button>
                    </div>
                    {current.reason === 'many-changes' ? (
                      <Button variant="secondary" onClick={() => void resolve(current, 'checked')} dataEl="LEAD-FLAG-CHECKED-BTN">
                        Mark as checked
                      </Button>
                    ) : (
                      <Button variant="secondary" onClick={() => void resolve(current, 'accept')} dataEl="LEAD-FLAG-ACCEPT-BTN">
                        Accept the figure
                      </Button>
                    )}
                    <span className={styles.suspend}>
                      <Button
                        variant="neutral"
                        href={`/lead/services/${encodeURIComponent(current.serviceId)}/suspend`}
                        dataEl="LEAD-FLAG-SUSPEND-LINK"
                      >
                        Suspend this service
                      </Button>
                    </span>
                  </div>
                </>
              ) : null}
            </section>
          </div>
        ) : null}
      </div>

      <p role="status" className={styles.notice}>
        {notice}
      </p>
      <p className={styles.footnote}>{FOOTNOTE}</p>

      <LeadPhonedDialog
        open={phoned !== null}
        serviceId={phoned?.serviceId ?? ''}
        serviceName={phoned?.serviceName ?? ''}
        onClose={() => setPhoned(null)}
      />
    </main>
  );
}
