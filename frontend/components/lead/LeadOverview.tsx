'use client';

import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { REFRESH_EVENTS } from '@/lib/board/useBoardFeed';
import { clockTime, dateTimeLine, servicesWord } from '@/lib/lead/format';
import { leadGet, leadPost, leadRead } from '@/lib/lead/browser';
import { parseOverview } from '@/lib/lead/parse';
import type { LeadOverview as Overview } from '@/lib/lead/types';
import { AttentionStat } from './AttentionStat';
import { ChaseCard } from './ChaseCard';
import { CoveringList } from './CoveringList';
import { DisclosureRow } from './DisclosureRow';
import { OldFigureCard } from './OldFigureCard';
import { UnderPressureList, UnderutilisedList } from './PressureLists';
import { SystemCounts } from './SystemCounts';
import styles from './LeadOverview.module.css';

// The shift lead's main page (W17, redesign LDR-01). It reads the overview from the BFF on load, every 60
// seconds and on a board update, and never shows an empty list for a read that failed (H-330): a failed first
// read says so and offers Try again; a failed later read keeps the last good page, dimmed, says when it is
// from, and switches off the actions that need fresh data until a read works.
//
// A chase opens in place (the board's state 2): the chosen card takes the stage with its full ladder and
// "Enter what they told me by phone" opens in a side sheet. The state has an address: ?chase=<service>, plus
// &sheet=phone for the sheet, so Back, a link and a reload land in the same place. The counts never animate.
// Only a service that newly needs chasing is announced, politely.

const REFRESH_MS = 60_000;
const STREAM_URL = '/api/bff/events';
const OVERVIEW_URL = '/api/bff/lead/overview';
const FLAGS_URL = '/api/bff/lead/flags?state=to-check';
const MINUTE_MS = 60_000;
const NEW_CHASE_WORDS = 'A service needs chasing';

// The stage's columns: list | stage | side. The side column is 340px of cards plus a 22px lead-in, so the
// column gap is the same at both stages. The stage collapses to nothing while the list is on show.
const TEMPLATES = ['minmax(0,1fr) 0px 362px', '0px minmax(0,1fr) 362px'];
const GAPS = ['0px', '0px'];

type Load =
  | { kind: 'loading' }
  | { kind: 'failed' }
  | { kind: 'ready'; overview: Overview; readAt: number; stale: boolean };

type Nav = { chase: string | null; sheet: boolean; last: string | null };

/** A row at the foot of the list that opens to its detail. Shown only when the page is given the data for it. */
export type LeadDisclosure = { id: string; title: string; hint: string; detail: ReactNode };

function remindPath(serviceId: string): string {
  return `/api/bff/lead/services/${encodeURIComponent(serviceId)}/remind`;
}

function readAddress(): { chase: string | null; sheet: boolean } {
  const params = new URLSearchParams(window.location.search);
  const chase = params.get('chase');
  return chase ? { chase, sheet: params.get('sheet') === 'phone' } : { chase: null, sheet: false };
}

function addressOf(chase: string | null, sheet: boolean): string {
  if (chase === null) return window.location.pathname;
  return `${window.location.pathname}?chase=${encodeURIComponent(chase)}${sheet ? '&sheet=phone' : ''}`;
}

/** The number of reports to check, from the flags answer, or null when it is not the answer we know. */
function toCheckFrom(body: unknown): number | null {
  const counts = (body as { counts?: { toCheck?: unknown } } | null)?.counts;
  const n = counts?.toCheck;
  return typeof n === 'number' && Number.isInteger(n) && n >= 0 ? n : null;
}

function WarningIcon() {
  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={styles.bannerIcon}
    >
      <path d="M12 3l10 18H2z" />
      <path d="M12 10v5M12 18h.01" />
    </svg>
  );
}

function LoadingLayout() {
  return (
    <Loading label="Loading the services to chase.">
      <div className={styles.loadingGrid}>
        <div className={styles.loadingMain}>
          <div className={styles.loadingStats}>
            <Skeleton shape="block" />
            <Skeleton shape="block" />
            <Skeleton shape="block" />
          </div>
          <div className={styles.loadingCard}>
            <Skeleton shape="title" width="62%" />
            <Skeleton shape="line" width="88%" />
            <Skeleton shape="block" />
          </div>
          <div className={styles.loadingCard}>
            <Skeleton shape="title" width="55%" />
            <Skeleton shape="line" width="80%" />
          </div>
        </div>
        <div className={styles.loadingSide}>
          <div className={styles.loadingCard}>
            <Skeleton shape="line" width="40%" />
            <Skeleton shape="line" />
            <Skeleton shape="line" />
            <Skeleton shape="line" />
          </div>
        </div>
      </div>
    </Loading>
  );
}

export function LeadOverview({ disclosures = [] }: { disclosures?: readonly LeadDisclosure[] }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [now, setNow] = useState<number>(() => Date.now());
  // What the last ask or reminder did, said on that service's own card so the press is never silent.
  const [feedback, setFeedback] = useState<{ serviceId: string; text: string; failed: boolean } | null>(null);
  const [askingId, setAskingId] = useState<string | null>(null);
  const [nav, setNav] = useState<Nav>({ chase: null, sheet: false, last: null });
  const [toCheck, setToCheck] = useState<number | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<{ key: number; words: string }>({ key: 0, words: '' });
  const seenChasing = useRef<ReadonlySet<string> | null>(null);
  const root = useRef<HTMLElement>(null);

  const reload = useCallback(async () => {
    const flags = leadRead(FLAGS_URL);
    try {
      const overview = parseOverview(await leadGet(OVERVIEW_URL));
      const ids = new Set(overview.chasing.map((item) => item.serviceId));
      const seen = seenChasing.current;
      if (seen !== null && overview.chasing.some((item) => !seen.has(item.serviceId))) {
        setAnnouncement((previous) => ({ key: previous.key + 1, words: NEW_CHASE_WORDS }));
      }
      seenChasing.current = ids;
      setLoad({ kind: 'ready', overview, readAt: Date.now(), stale: false });
    } catch {
      // Keep the last good overview, if there is one, and say it is out of date. A failed read is never an
      // empty list.
      setLoad((previous) => (previous.kind === 'ready' ? { ...previous, stale: true } : { kind: 'failed' }));
    }
    const answer = await flags;
    if (answer.ok) {
      const count = toCheckFrom(answer.body);
      if (count !== null) setToCheck(count);
    }
  }, []);

  const apply = useCallback((address: { chase: string | null; sheet: boolean }) => {
    setNav((previous) => ({ ...address, last: address.chase ?? previous.last }));
  }, []);

  useEffect(() => {
    // The first read is started by the timer's first tick and by the stream, not synchronously here: a read
    // that answers at once would otherwise set state inside this effect's body. The address is read there too.
    const first = setTimeout(() => {
      apply(readAddress());
      void reload();
    }, 0);
    const timer = setInterval(() => void reload(), REFRESH_MS);
    const clock = setInterval(() => setNow(Date.now()), MINUTE_MS);
    const onPop = () => apply(readAddress());
    window.addEventListener('popstate', onPop);
    let stream: EventSource | null = null;
    if (typeof EventSource !== 'undefined') {
      stream = new EventSource(STREAM_URL);
      for (const name of REFRESH_EVENTS) stream.addEventListener(name, () => void reload());
    }
    return () => {
      clearTimeout(first);
      clearInterval(timer);
      clearInterval(clock);
      window.removeEventListener('popstate', onPop);
      stream?.close();
    };
  }, [reload, apply]);

  function go(chase: string | null, sheet: boolean) {
    apply({ chase, sheet });
    window.history.pushState(null, '', addressOf(chase, sheet));
  }

  function focusSoon(find: () => HTMLElement | null | undefined) {
    requestAnimationFrame(() => find()?.focus());
  }

  // The sheet closes and the card stays open: focus goes to the card's own phone button.
  function closeSheet() {
    go(nav.chase, false);
    focusSoon(() =>
      root.current?.querySelector<HTMLElement>('[data-layer="current"] [data-el="LEAD-CHASE-PHONED-BTN"]'),
    );
  }

  // The card closes: focus goes back to that service's button in the list.
  function closeChase() {
    const id = nav.chase;
    go(null, false);
    focusSoon(() => {
      const wrapper = Array.from(root.current?.querySelectorAll('[data-service-id]') ?? []).find(
        (element) => element.getAttribute('data-service-id') === id,
      );
      return wrapper?.querySelector<HTMLElement>('[data-el="LEAD-CHASE-PHONED-BTN"]');
    });
  }

  async function remind(serviceId: string) {
    setFeedback(null);
    const result = await leadPost(remindPath(serviceId));
    if (result.ok) {
      setFeedback({ serviceId, text: 'Reminder sent', failed: false });
    } else {
      // The back end answers 409 when no reminder is waiting: say so, so the press is not silent (DEC-1335).
      setFeedback({
        serviceId,
        failed: true,
        text:
          result.status === 409
            ? 'No reminder is waiting to send. Ask for capacity now instead.'
            : 'The reminder could not be sent. Try again.',
      });
    }
  }

  async function askNow(serviceId: string) {
    setFeedback(null);
    setAskingId(serviceId);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/ask`);
    setAskingId(null);
    if (result.ok) {
      setFeedback({ serviceId, text: 'Asked for capacity. The text is on its way.', failed: false });
    } else {
      setFeedback({
        serviceId,
        failed: true,
        text:
          result.status === 409
            ? 'A capacity request is already due for this service.'
            : 'The request could not be sent. Try again.',
      });
    }
  }

  function feedbackFor(serviceId: string): { text: string; failed: boolean } | null {
    return feedback !== null && feedback.serviceId === serviceId ? feedback : null;
  }

  async function retry() {
    setRetrying(true);
    await reload();
    setRetrying(false);
  }

  const ready = load.kind === 'ready' ? load : null;
  const overview = ready?.overview ?? null;
  const stale = ready?.stale === true;
  const chasing = overview?.chasing ?? [];
  const openItem = chasing.find((item) => item.serviceId === nav.chase);
  const stageItem = chasing.find((item) => item.serviceId === (nav.chase ?? nav.last));
  const stage = openItem === undefined ? 0 : 1;

  return (
    <main className={styles.page} ref={root}>
      <PageHeader title="Your shift">
        <time className={styles.time} dateTime={new Date(now).toISOString()}>
          {dateTimeLine(now)}
        </time>
      </PageHeader>

      {/* Which board this is (TEN-069), with the way to the network's System now when there is one (W17). */}
      <OwnScopeHeader ownHref="/lead" networkHref="/network/system-now" />

      {load.kind === 'failed' ? (
        <div role="alert" className={styles.banner}>
          <WarningIcon />
          <div className={styles.bannerText}>
            <p className={styles.bannerTitle}>We could not load the shift lead page. Try again shortly.</p>
          </div>
          <Button variant="secondary" busy={retrying} onClick={() => void retry()} dataEl="LEAD-RETRY-BTN">
            Try again
          </Button>
        </div>
      ) : null}

      {ready !== null && stale ? (
        <div role="alert" className={styles.banner}>
          <WarningIcon />
          <div className={styles.bannerText}>
            <p className={styles.bannerTitle}>We could not refresh this page</p>
            <p className={styles.bannerLine}>
              {`You are looking at what we had at ${clockTime(new Date(ready.readAt).toISOString())}. Figures may have changed.`}
            </p>
          </div>
          <Button variant="secondary" busy={retrying} onClick={() => void retry()} dataEl="LEAD-RETRY-BTN">
            Try again
          </Button>
        </div>
      ) : null}

      {load.kind === 'loading' ? <LoadingLayout /> : null}

      {overview !== null ? (
        <StageGrid stage={stage} templates={TEMPLATES} gaps={GAPS} className={styles.grid}>
          <StageArea name="list">
            <StageLayer index={0} current={stage}>
              <fieldset className={styles.plain} disabled={stale} data-stale={stale || undefined}>
                <div className={styles.listBody}>
                  <ul className={styles.stats} aria-label="Needs you first">
                    <li>
                      <AttentionStat
                        count={chasing.length}
                        label={`${servicesWord(chasing.length)} to chase`}
                        hint="overdue now"
                        urgent
                      />
                    </li>
                    {toCheck !== null ? (
                      <li>
                        <AttentionStat
                          count={toCheck}
                          label={`${toCheck === 1 ? 'report' : 'reports'} to check`}
                          hint="looks wrong"
                        />
                      </li>
                    ) : null}
                  </ul>

                  <section aria-labelledby="lead-chase-heading" data-el="LEAD-CHASE" className={styles.group}>
                    {chasing.length === 0 ? (
                      <div className={styles.quiet}>
                        <span className={styles.quietMark} aria-hidden="true">
                          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
                            <path d="M5 12.5l4.5 4.5L19 7.5" />
                          </svg>
                        </span>
                        <div>
                          <h2 id="lead-chase-heading" className={styles.quietTitle}>
                            Nothing needs chasing
                          </h2>
                          <p className={styles.quietLine}>
                            Every service has reported on time. This page updates by itself.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <>
                        <h2 id="lead-chase-heading" className={styles.srOnly}>
                          {`${chasing.length} ${servicesWord(chasing.length)} ${chasing.length === 1 ? 'needs' : 'need'} chasing`}
                        </h2>
                        <div className={styles.stack}>
                          {chasing.map((item) => (
                            <div key={item.serviceId} data-service-id={item.serviceId}>
                              <ChaseCard
                                item={item}
                                onEnterPhoned={() => go(item.serviceId, true)}
                                onAsk={() => void askNow(item.serviceId)}
                                onRemind={() => void remind(item.serviceId)}
                                asking={askingId === item.serviceId}
                                feedback={feedbackFor(item.serviceId)}
                              />
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </section>

                  {overview.gettingOld.length > 0 ? (
                    <section aria-labelledby="lead-old-heading" data-el="LEAD-OLD" className={styles.group}>
                      <h2 id="lead-old-heading" className={styles.srOnly}>
                        Getting old
                      </h2>
                      <div className={styles.stack}>
                        {overview.gettingOld.map((item) => (
                          <OldFigureCard
                            key={item.serviceId}
                            item={item}
                            now={now}
                            disabled={stale}
                            onAsk={() => void remind(item.serviceId)}
                            feedback={feedbackFor(item.serviceId)}
                          />
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {chasing.length === 0 ? (
                    <div className={styles.setup}>
                      <div className={styles.setupText}>
                        <p className={styles.setupTitle}>Set up another service</p>
                        <p className={styles.setupLine}>Add a service that reports for itself, or invite its lead to set it up.</p>
                      </div>
                      <Button variant="secondary" href="/lead/services/new" dataEl="LEAD-ADD-SERVICE-LINK">
                        Add a service
                      </Button>
                      <Button variant="secondary" href="/lead/services/invite" dataEl="LEAD-INVITE-SERVICE-LINK">
                        Invite a service
                      </Button>
                    </div>
                  ) : null}

                  {disclosures.length > 0 ? (
                    <div className={styles.rows}>
                      {disclosures.map((row) => (
                        <DisclosureRow
                          key={row.id}
                          open={openRow === row.id}
                          onToggle={() => setOpenRow((current) => (current === row.id ? null : row.id))}
                          title={row.title}
                          hint={row.hint}
                        >
                          {row.detail}
                        </DisclosureRow>
                      ))}
                    </div>
                  ) : null}
                </div>
              </fieldset>
            </StageLayer>
          </StageArea>

          <StageArea name="stage">
            <StageLayer index={1} current={stage}>
              {stageItem !== undefined ? (
                <fieldset className={styles.plain} disabled={stale}>
                  <div className={styles.listBody}>
                    <ChaseCard
                      item={stageItem}
                      onEnterPhoned={() => go(stageItem.serviceId, true)}
                      onAsk={() => void askNow(stageItem.serviceId)}
                      onRemind={() => void remind(stageItem.serviceId)}
                      asking={askingId === stageItem.serviceId}
                      feedback={feedbackFor(stageItem.serviceId)}
                      onClose={closeChase}
                    />
                  </div>
                </fieldset>
              ) : null}
            </StageLayer>
          </StageArea>

          <StageArea name="side">
            <div className={styles.side}>
              <div className={styles.sideBody}>
                <SystemCounts counts={overview.counts} reportingToday={overview.reportingToday} />
                {overview.underPressure === undefined ? null : <UnderPressureList items={overview.underPressure} />}
                {overview.underutilised === undefined ? null : <UnderutilisedList items={overview.underutilised} />}
                <CoveringList items={overview.covering} />
              </div>
            </div>
          </StageArea>
        </StageGrid>
      ) : null}

      <nav aria-label="Shift lead pages" className={styles.links}>
        <a href="/lead/screens">Wall screens</a>
        <a href="/planning/coverage">Where coverage runs out</a>
      </nav>

      {/* New chases only, politely; never a count. A new span each time, so the same words are said again. */}
      <div aria-live="polite" className={styles.srOnly} data-el="LEAD-ANNOUNCE">
        {announcement.words === '' ? null : <span key={announcement.key}>{announcement.words}</span>}
      </div>

      <LeadPhonedDialog
        open={openItem !== undefined && nav.sheet}
        serviceId={openItem?.serviceId ?? ''}
        serviceName={openItem?.name ?? ''}
        onClose={closeSheet}
        onRecorded={() => void reload()}
      />
    </main>
  );
}
