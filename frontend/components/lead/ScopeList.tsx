'use client';

import { useEffect, useState } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { bffGet } from '@/lib/bff/client';
import { canInvite, categoryLabel, flagLabel, parseScopeList, stateLabel } from '@/lib/registration/model';
import type { ScopeEntry, ScopeFlag, ScopeRegistrationState } from '@/lib/registration/types';
import { AddScopeForm, type AddedScope } from './AddScopeForm';
import styles from './ScopeList.module.css';

// The services that may be invited (W28, ui-screens ApprovalWeb1 screen 1). The list is the only
// place an invitation can start from, so only an in-pilot service not yet invited shows Invite.
// The add panel is opened by the person; until then the list has the full width.

type Filter = 'all' | ScopeFlag;

const FILTERS: readonly { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'in-pilot', label: 'In pilot' },
  { key: 'later', label: 'Later' },
  { key: 'out-of-scope', label: 'Out of scope' },
];

type Notice = AddedScope;

// The shape and tone of each lifecycle state. The word is the meaning; the shape repeats it (never colour alone).
const MARKS: Record<ScopeRegistrationState, { shape: string; tone: string }> = {
  live: { shape: 'solid', tone: 'primary' },
  paused: { shape: 'dashedSquare', tone: 'limited' },
  'in-review': { shape: 'ring', tone: 'primary' },
  reverify: { shape: 'diamond', tone: 'limited' },
  'not-invited': { shape: 'dashed', tone: 'unknown' },
  invited: { shape: 'ring', tone: 'primaryDark' },
  'not-approved': { shape: 'cross', tone: 'closed' },
};

function StatusMark({ state }: { state: ScopeRegistrationState }) {
  const mark = MARKS[state];
  return (
    <span className={styles.state} data-tone={mark.tone}>
      <span className={`${styles.shape} ${styles[mark.shape] ?? ''}`} aria-hidden="true" />
      <span>{stateLabel(state)}</span>
    </span>
  );
}

export function ScopeList() {
  const [entries, setEntries] = useState<ScopeEntry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await bffGet('/api/bff/scope', parseScopeList);
      if (!current) return;
      if (result.ok) {
        setEntries(result.data.entries);
        setFailed(false);
      } else {
        setFailed(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [version]);

  const added = (entry: AddedScope) => {
    setAdding(false);
    setNotice(entry);
    setVersion((n) => n + 1);
  };

  const retry = () => {
    setFailed(false);
    setEntries(null);
    setVersion((n) => n + 1);
  };

  const counts = (key: Filter) => (entries === null ? 0 : key === 'all' ? entries.length : entries.filter((e) => e.flag === key).length);

  const visible = entries === null ? [] : filter === 'all' ? entries : entries.filter((e) => e.flag === filter);

  // The notice: its Invite link goes to the new service only when it is in the pilot and the back end gave its id.
  const noticeInvite = notice !== null && notice.flag === 'in-pilot' && notice.serviceId !== null;

  let body;
  if (failed) {
    body = (
      <Banner tone="warning" title="The scope list could not be loaded. Try again shortly.">
        <Button variant="secondary" dataEl="LEAD-SCOPE-RETRY-BTN" onClick={retry}>
          Try again
        </Button>
      </Banner>
    );
  } else if (entries === null) {
    body = (
      <Loading label="Loading the scope list.">
        <SkeletonRows count={3} />
      </Loading>
    );
  } else if (entries.length === 0) {
    body = (
      <div className={styles.empty}>
        <p className={styles.emptyTitle}>No services are in the scope list yet.</p>
        <p className={styles.emptyText}>Add a service to start the list. Only services on the list can be invited.</p>
      </div>
    );
  } else if (visible.length === 0) {
    body = (
      <div className={styles.empty}>
        <p className={styles.emptyTitle}>{filter === 'all' ? 'No services to show.' : `No services are marked ${flagLabel(filter)} yet.`}</p>
        <p className={styles.emptyText}>Choose All to see every service on the list.</p>
      </div>
    );
  } else {
    body = (
      <ul className={styles.list} aria-label="Services in scope">
        {visible.map((entry) => (
          <li key={entry.serviceId} className={styles.row} data-el="LEAD-SCOPE-ROW">
            <div className={styles.rowText}>
              <p className={styles.name}>{entry.name}</p>
              <p className={styles.meta}>
                {categoryLabel(entry.category)}
                {entry.flag !== 'in-pilot' ? (
                  <>
                    {' · '}
                    <b>{flagLabel(entry.flag)}</b>
                  </>
                ) : null}
              </p>
            </div>
            <StatusMark state={entry.registrationState} />
            <div className={styles.action}>
              {canInvite(entry) ? (
                <Button
                  variant="secondary"
                  href={`/lead/reporters/invite?service=${encodeURIComponent(entry.serviceId)}`}
                  dataEl="LEAD-SCOPE-INVITE-LINK"
                >
                  Invite
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <main className={styles.page}>
      <PageHeader title="Services in scope">
        <p className={styles.lede}>You can only invite services on this list.</p>
      </PageHeader>

      <div className={`${styles.layout} ${adding ? styles.withPanel : ''}`}>
        <section aria-label="Services" className={styles.listColumn}>
          <div role="group" aria-label="Show services by where they stand" className={styles.filters}>
            {FILTERS.map((option) => (
              <button
                key={option.key}
                type="button"
                className={styles.filter}
                aria-pressed={filter === option.key}
                onClick={() => setFilter(option.key)}
              >
                {option.label} <span className={styles.count}>{counts(option.key)}</span>
              </button>
            ))}
          </div>

          {notice !== null ? (
            <div role="status" className={styles.success}>
              <div className={styles.successText}>
                <p className={styles.successTitle}>Added {notice.name} to the scope list.</p>
                {notice.flag === 'in-pilot' ? <p>It can be invited now.</p> : null}
              </div>
              {noticeInvite ? (
                <Button
                  variant="secondary"
                  href={`/lead/reporters/invite?service=${encodeURIComponent(notice.serviceId ?? '')}`}
                  dataEl="LEAD-SCOPE-NOTICE-INVITE-LINK"
                >
                  Invite
                </Button>
              ) : null}
            </div>
          ) : null}

          {body}

          {!adding ? (
            <div>
              <Button
                variant="secondary"
                dataEl="LEAD-SCOPE-ADD-BTN"
                onClick={() => {
                  setNotice(null);
                  setAdding(true);
                }}
              >
                Add a service to the scope list
              </Button>
            </div>
          ) : null}
        </section>

        {adding ? <AddScopeForm onAdded={added} onCancel={() => setAdding(false)} /> : null}
      </div>
    </main>
  );
}
