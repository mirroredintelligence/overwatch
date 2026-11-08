'use client';

import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ProgressBar5 } from '@/components/blocks/ProgressBar5';
import { Icon } from '@/components/shell/icons';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { useOperatorRead } from '@/lib/operator/browser';
import { deriveFunnel, type Consent, type Funnel } from '@/lib/operator/funnel';
import type { OperatorRole } from '@/lib/operator/session';
import type { parseTenantDetail, parseTenantList } from '@/lib/operator/views';
import { organisationTypeWord, TENANT_STATUS_WORD } from '@/lib/operator/words';
import styles from '@/components/admin/admin.module.css';
import ds from './TenantList.module.css';

// The console's first page (TEN-083, board O2): the organisations. The operator sees one card per organisation,
// with its type, ODS code and address, its status in words, and for one being set up its five parts and the next
// step. Each card reads its own detail only once it is in view (the list has no progress). A support person sees
// the name and the status (the BFF has dropped the rest) and can ask to look into an active one, as a table.

type List = ReturnType<typeof parseTenantList>;
type Row = List['tenants'][number];
type Detail = ReturnType<typeof parseTenantDetail>;
type Filter = 'all' | 'provisioning' | 'active';

const FILTERS: readonly { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'provisioning', label: 'Being set up' },
  { id: 'active', label: 'Live' },
];

const CARD_STATUS: Record<string, { variant: StatusTagVariant; word: string }> = {
  provisioning: { variant: 'waiting', word: 'Being set up' },
  active: { variant: 'live', word: 'Live' },
  suspended: { variant: 'problem', word: 'Suspended' },
  offboarding: { variant: 'paused', word: 'Closing' },
  offboarded: { variant: 'closed', word: 'Closed' },
  purged: { variant: 'closed', word: 'Removed' },
};

const SHORT_DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });

export function TenantList({ role }: { role: OperatorRole }) {
  return role === 'platform-operator' ? <OperatorOrganisations /> : <SupportOrganisations />;
}

function OperatorOrganisations() {
  const { state, reload } = useOperatorRead<List>('/api/bff/platform/tenants');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const all = state.status === 'ok' ? state.data.tenants : [];
  const needle = query.trim().toLowerCase();
  const shown = all.filter(
    (t) => (filter === 'all' || t.status === filter) && (needle === '' || t.displayName.toLowerCase().includes(needle) || (t.host ?? '').toLowerCase().includes(needle)),
  );
  const count = (id: Filter) => (id === 'all' ? all.length : all.filter((t) => t.status === id).length);

  return (
    <main className={ds.page}>
      <h1 className={ds.visuallyHidden}>Tenants</h1>
      <div className={ds.top}>
        {all.length > 0 ? (
          <>
            <div className={ds.search}>
              <svg className={ds.searchIcon} width="18" height="18" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
                <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
              <input
                type="search"
                className={ds.searchInput}
                aria-label="Find an organisation"
                placeholder="Find an organisation"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className={ds.chips} role="group" aria-label="Show">
              {FILTERS.map((f) => (
                <button key={f.id} type="button" className={ds.chip} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                  {`${f.label} · ${count(f.id)}`}
                </button>
              ))}
            </div>
          </>
        ) : null}
        <div className={ds.create}>
          <Button variant="primary" href="/operator/tenants/new" dataEl="OP-CREATE-TENANT-BTN">
            Create an organisation
          </Button>
        </div>
      </div>

      {state.status === 'loading' ? (
        <Loading label="Loading the organisations.">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}
      {state.status === 'failed' ? (
        <div role="alert" className={ds.problem}>
          <p className={ds.status}>We could not load the organisations.</p>
          <Button variant="secondary" onClick={reload}>
            Try again
          </Button>
        </div>
      ) : null}
      {state.status === 'ok' && all.length === 0 ? (
        <section className={ds.empty} aria-labelledby="no-organisations">
          <h2 id="no-organisations" className={ds.emptyTitle}>
            There are no organisations yet.
          </h2>
          <p className={ds.text}>
            Create the first one, then give it an address, bind its directory, map the groups that sign in and add its first administrator to the administrators’ group. It does nothing until you activate it.
          </p>
        </section>
      ) : null}
      {all.length > 0 && shown.length === 0 ? <p role="status" className={ds.status}>No organisation matches. Try another name or address, or show all.</p> : null}
      {shown.length > 0 ? (
        <ul className={ds.list} aria-label="Organisations">
          {shown.map((t) => (
            <OrganisationCard key={t.id} tenant={t} />
          ))}
        </ul>
      ) : null}
    </main>
  );
}

/**
 * One organisation as a card. It reads its detail only once the card is in view (or at once where nothing can watch
 * for that). The card is the same element tree before and after: only what it is given changes, so what is on the
 * screen is not torn down and put up again when the detail arrives.
 */
function OrganisationCard({ tenant }: { tenant: Row }) {
  const ref = useRef<HTMLLIElement>(null);
  const seen = useSeen(ref);
  const detail = useOperatorRead<Detail>(seen ? `/api/bff/platform/tenants/${tenant.id}` : null);
  const consent = useOperatorRead<Consent>(seen && tenant.status === 'provisioning' ? `/api/bff/platform/tenants/${tenant.id}/admin-consent` : null);
  let ods: string | null = null;
  let setUp: ReactNode = null;
  if (detail.state.status === 'failed') {
    setUp = <p className={ds.progressText}>We could not read this organisation’s progress.</p>;
  } else if (detail.state.status === 'ok') {
    ods = detail.state.data.tenant.odsCode;
    setUp = <SetUpProgress funnel={deriveFunnel(detail.state.data, consent.state)} />;
  }
  return (
    <li ref={ref} className={ds.card}>
      <CardContent tenant={tenant} ods={ods} setUp={setUp} />
    </li>
  );
}

function CardContent({ tenant, ods, setUp }: { tenant: Row; ods: string | null; setUp: ReactNode }) {
  const status = CARD_STATUS[tenant.status] ?? { variant: 'todo' as const, word: tenant.status };
  const meta = [tenant.organisationType === null ? null : organisationTypeWord(tenant.organisationType), ods, tenant.host].filter((part): part is string => Boolean(part));
  const live = tenant.status === 'active';
  const provisioning = tenant.status === 'provisioning';
  return (
    <>
      <span className={ds.icon} aria-hidden="true">
        <Icon name="building" size={24} />
      </span>
      <div className={ds.body}>
        <h2 className={ds.name}>{tenant.displayName}</h2>
        {meta.length > 0 ? <p className={ds.meta}>{meta.join(' · ')}</p> : null}
      </div>
      {live || provisioning ? (
        <div className={ds.progress}>
          {live ? <p className={ds.progressText}>{tenant.activatedAt === null ? 'Live' : `Live since ${SHORT_DATE.format(new Date(tenant.activatedAt))}`}</p> : null}
          {provisioning ? setUp ?? <span className={ds.placeholder} aria-hidden="true" /> : null}
        </div>
      ) : null}
      <StatusTag variant={status.variant}>{status.word}</StatusTag>
      <a className={ds.open} href={`/operator/tenants/${tenant.id}`}>
        Open{' '}<span className={ds.visuallyHidden}>{`${tenant.displayName}`}</span>
      </a>
    </>
  );
}

/** The five parts, a bar, and the next step in words. */
function SetUpProgress({ funnel }: { funnel: Funnel }) {
  const done = funnel.phases.filter((p) => p.done).length;
  return (
    <>
      <ProgressBar5 done={done} />
      <p className={ds.progressText}>
        {`${done} of ${funnel.phases.length} parts · `}
        <b>{nextStepWords(funnel)}</b>
      </p>
    </>
  );
}

function nextStepWords(funnel: Funnel): string {
  if (funnel.canGoLive) return 'Ready to go live';
  const next = funnel.phases.find((p) => p.id === funnel.nextPhase);
  if (next === undefined) return '';
  if (next.state === 'waiting') return next.id === 'approval' ? 'Waiting for their administrator' : 'Waiting for them';
  return `Next: ${next.title}`;
}

/** True once the element has come into view (it stays true). Without an observer, true at once. */
function useSeen(ref: RefObject<HTMLElement | null>): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (seen || el === null) return;
    if (typeof IntersectionObserver === 'undefined') {
      void Promise.resolve().then(() => setSeen(true));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin: '200px 0px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, seen]);
  return seen;
}

function SupportOrganisations() {
  const { state } = useOperatorRead<List>('/api/bff/platform/tenants');
  return (
    <main className={styles.page}>
      <div className={styles.headRow}>
        <div>
          <h1 className={styles.title}>Organisations</h1>
          <p className={styles.muted}>One row per organisation. Ask to look into an active one.</p>
        </div>
      </div>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the organisations.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the organisations.
        </p>
      ) : null}
      {state.status === 'ok' && state.data.tenants.length === 0 ? (
        <section className={styles.empty} aria-labelledby="no-organisations">
          <h2 id="no-organisations" className={styles.emptyTitle}>
            There are no organisations yet.
          </h2>
          <p className={styles.text}>When a platform operator creates one and activates it, you can ask to look into it here.</p>
        </section>
      ) : null}
      {state.status === 'ok' && state.data.tenants.length > 0 ? (
        <div className={styles.scroll}>
          <table className={`${styles.table} ${styles.stackTable}`}>
            <caption>Organisations</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                <th scope="col">Ask to look in</th>
              </tr>
            </thead>
            <tbody>
              {state.data.tenants.map((t) => (
                <tr key={t.id}>
                  <th scope="row">{t.displayName}</th>
                  <td data-label="Status">
                    <span className={t.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{TENANT_STATUS_WORD[t.status] ?? t.status}</span>
                  </td>
                  <td data-label="Ask to look in">
                    {t.status === 'active' ? (
                      <a className={styles.link} href={`/operator/support/new?for=${t.id}`}>
                        Ask for access{' '}<span className={styles.srOnly}>{`to ${t.displayName}`}</span>
                      </a>
                    ) : (
                      '-'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  );
}
