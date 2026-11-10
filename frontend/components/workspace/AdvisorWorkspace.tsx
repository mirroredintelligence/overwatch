'use client';

import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { PostcodePicker } from '@/components/advisor/PostcodePicker';
import { AGE_BANDS, NEEDS, URGENCIES, type NeedCode } from '@/lib/advisor/codes';
import { normalisePostcode, outwardCode } from '@/lib/advisor/postcode';
import { locatePostcode, type PostcodeLocation, suggestPostcodes } from '@/lib/advisor/postcodeSuggest';
import { findServices } from '@/lib/advisor/v2/browser';
import { orderServices, type FindRead, type FoundService } from '@/lib/advisor/v2/find';
import { overdueText } from '@/lib/lead/format';
import type { DialogContext } from '@/lib/workspace/dialog';
import { parseAdvisorUrl, workspaceHref } from '@/lib/workspace/url';
import { CriteriaSummary } from './CriteriaSummary';
import styles from './AdvisorWorkspace.module.css';
import { MapPane } from './MapPane';
import { NotSuitableList } from './NotSuitableList';
import { ResultsList, serviceHref } from './ResultsList';
import { TriageCard } from './TriageCard';
import { WorkspacePage } from './WorkspacePage';
import { useWorkspace, type Opened } from './WorkspaceProvider';

// Find a service inside the workspace (DEC-1376, WS-ADV). The intake is the assistant's triage card in the thread (age
// and postcode, then need and timeframe); the search starts by itself once the criteria are complete; the results are
// the canvas. The URL holds only view, step, group and order. The criteria live in the provider and are never in a link.
// The finder's behaviour (postcode suggestions and lookup, the search, the group cards and the order) is the same as
// FindService, which this does not import.

const TITLE = 'Find a service';
const WAIT_MS = 250;
const POSTCODE_ID = 'ws-postcode';
const POSTCODE_LIST_ID = 'ws-postcode-suggestions';
const POSTCODE_HELP_ID = 'ws-postcode-help';
const POSTCODE_HELP = 'Enter a full postcode, for example DT4 8XX.';
const IDLE_STATUS = 'Choose the postcode, age, need and time to list services.';
const SEARCHING = 'Searching.';
const FAILED = 'The services could not be searched. Change a choice to try again, or phone the services.';
const NONE = 'No service takes this patient on its criteria. Phone to confirm, or change the criteria.';
const NOT_PLACED = 'The postcode could not be placed, so no travel time is shown. Services are listed by name.';
const AGE_HREF = workspaceHref('advisor.intake.age');
const NEED_HREF = workspaceHref('advisor.intake.need');
const RESULTS_HREF = workspaceHref('advisor.results');
const WHY_TITLE = 'Not suitable, and why';

type Search = { key: string; kind: 'searching' } | { key: string; kind: 'failed' } | { key: string; kind: 'done'; read: FindRead };

function needLabel(code: NeedCode): string {
  return NEEDS.find((item) => item.code === code)?.label ?? code;
}

// What the thread remembers about the service the person opened (WS-DATA). No report yet gives an empty update line.
function openedOf(service: FoundService): Opened {
  const noReport = service.dataAgeSeconds === null;
  return {
    serviceName: service.name,
    updated: service.dataAgeSeconds === null ? '' : `${overdueText(Math.floor(service.dataAgeSeconds / 60))} ago`,
    stale: service.figureUnavailable || service.staleWarning,
    noReport,
  };
}

export function AdvisorWorkspace(): ReactElement {
  const router = useRouter();
  const url = parseAdvisorUrl(useSearchParams().toString());
  const { criteria, setCriteria, criteriaComplete, remember, visit } = useWorkspace();
  const { age, postcode, needs, urgency } = criteria;
  const { view: pageView, step, group, order } = url;

  const [result, setResult] = useState<Search | null>(null);
  const [located, setLocated] = useState<PostcodeLocation | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  // The last criteria a search was started for, so the same criteria are never searched twice.
  const lastKey = useRef<string | null>(null);

  // The results and the need step are the list view; a map or why view is not live, so it is shown as the list.
  const view: 'find' | 'list' = pageView === 'find' ? 'find' : 'list';
  const full = normalisePostcode(postcode);
  const district = full === null ? null : outwardCode(full);
  const ageLabel = AGE_BANDS.find((band) => band.code === age)?.label ?? null;
  const urgencyLabel = URGENCIES.find((item) => item.code === urgency)?.label ?? null;
  const ageOk = age !== null && full !== null;
  const onResults = view === 'list' && criteriaComplete;
  const intakeStep: 'age' | 'need' = (view === 'list' || step === 'need') && ageOk ? 'need' : 'age';

  // A list without complete criteria, or the need step without an age and a full postcode, goes back to the intake.
  const needsGate = (view === 'list' && !criteriaComplete) || (view === 'find' && step === 'need' && !ageOk);
  const gateTarget: string | null = needsGate ? (ageOk ? NEED_HREF : AGE_HREF) : null;

  // The search runs on the need step once the criteria are complete. The key is what the search depends on.
  const searching = view === 'find' && step === 'need' && criteriaComplete;
  const needsKey = [...needs].sort().join(',');
  const searchKey = `${full ?? ''}|${age ?? ''}|${needsKey}|${urgency ?? ''}`;
  const current = result !== null && result.key === searchKey ? result : null;
  const read = current?.kind === 'done' ? current.read : null;
  const outcome: 'none' | 'failed' | 'done' = current === null || current.kind === 'searching' ? 'none' : current.kind;
  const groups: Group[] = read === null ? [] : groupsOf(read.services);
  const chosen = onResults ? (groups.find((item) => item.category === group) ?? null) : null;
  const count = read?.services.length ?? 0;
  const notFound = read?.notFound === true;
  const totals = read?.groupTotals ?? {};

  const summaryLine =
    criteriaComplete && ageLabel !== null && district !== null && urgencyLabel !== null
      ? [ageLabel, district, needs.map(needLabel).join(', '), urgencyLabel].join(' · ')
      : null;

  let status = IDLE_STATUS;
  if (current?.kind === 'searching' || (searching && current === null)) status = SEARCHING;
  if (onResults && read !== null) {
    status =
      chosen === null
        ? `${groups.length} service groups · ${count} services`
        : `${chosen.services.length} matching services`;
  }

  const helpText =
    located === null
      ? full !== null
        ? 'Postcode accepted.'
        : POSTCODE_HELP
      : located.status === 'found'
        ? `Found: ${located.lat.toFixed(5)}, ${located.lon.toFixed(5)} (OS Places).`
        : located.status === 'not-found'
          ? 'Not found. Check the postcode.'
          : 'The postcode lookup is unavailable. The search still uses the postcode as typed.';

  // A redirect to the intake, once for each target.
  useEffect(() => {
    if (gateTarget !== null) router.replace(gateTarget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gateTarget]);

  // The intake turns of the assistant. Each depends only on primitive values.
  useEffect(() => {
    if (!onResults && intakeStep === 'age') visit('advisor.intake.age', {});
  }, [visit, onResults, intakeStep]);

  useEffect(() => {
    if (!onResults && intakeStep === 'need') {
      visit('advisor.intake.need', { age: ageLabel ?? '', district: district ?? '' });
    }
  }, [visit, onResults, intakeStep, ageLabel, district]);

  // The search: once per distinct criteria, 250 ms after the last change, and then the results page.
  useEffect(() => {
    if (!searching || full === null || age === null || urgency === null) return;
    if (lastKey.current === searchKey) return;
    let live = true;
    const timer = setTimeout(() => {
      lastKey.current = searchKey;
      setResult({ key: searchKey, kind: 'searching' });
      findServices({ postcode: full, ageBand: age, needs, urgency }).then((found) => {
        // The answer is kept for its criteria even when the person has moved on; the push happens only while live.
        setResult(found === null ? { key: searchKey, kind: 'failed' } : { key: searchKey, kind: 'done', read: found });
        if (live) router.push(RESULTS_HREF);
      });
    }, WAIT_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // The criteria are compared by searchKey; the values read here are the ones of the render that changed it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searching, searchKey]);

  // The results turn: its count, order and whether the search failed or the postcode could not be placed.
  useEffect(() => {
    if (!onResults || outcome === 'none') return;
    const context: DialogContext =
      outcome === 'failed'
        ? { failed: true, count: 0, order, summaryLine }
        : { count, order, summaryLine, ...(notFound ? { postcodeNotPlaced: true } : {}) };
    visit('advisor.results', context);
  }, [visit, onResults, outcome, count, notFound, order, summaryLine]);

  function onPostcodeType(typed: string) {
    setCriteria({ postcode: typed });
    setLocated(null);
    void suggestPostcodes(typed).then(setSuggestions);
  }

  function onPostcodePick(picked: string) {
    setCriteria({ postcode: picked });
    setSuggestions([]);
    setLocated(null);
    void locatePostcode(picked).then(setLocated);
  }

  // The same lookup as the finder: a full postcode is normalised, and its position is looked up. A lookup that cannot
  // answer never blocks the search, which uses the postcode as typed.
  function onPostcodeBlur() {
    const normal = normalisePostcode(postcode);
    if (normal === null) {
      setLocated(null);
      return;
    }
    setCriteria({ postcode: normal });
    void locatePostcode(normal).then(setLocated);
  }

  function toggleNeed(code: NeedCode) {
    setCriteria({ needs: needs.includes(code) ? needs.filter((item) => item !== code) : [...needs, code] });
  }

  const postcodeSlot = (
    <div className={styles.postcode}>
      <label htmlFor={POSTCODE_ID} className={styles.label}>
        Postcode
      </label>
      <PostcodePicker
        id={POSTCODE_ID}
        listId={POSTCODE_LIST_ID}
        value={postcode}
        options={suggestions}
        invalid={false}
        describedBy={POSTCODE_HELP_ID}
        dataEl="ADV-V2-POSTCODE"
        onType={onPostcodeType}
        onPick={onPostcodePick}
        onBlur={onPostcodeBlur}
      />
      <p id={POSTCODE_HELP_ID} className={styles.help} aria-live="polite" data-el="ADV-V2-POSTCODE-LOOKUP">
        {helpText}
      </p>
    </div>
  );

  const card = onResults ? undefined : (
    <TriageCard
      step={intakeStep}
      age={age}
      needs={needs}
      urgency={urgency}
      postcodeSlot={postcodeSlot}
      canNext={ageOk}
      onAge={(code) => setCriteria({ age: code })}
      onToggleNeed={toggleNeed}
      onUrgency={(code) => setCriteria({ urgency: code })}
      onNext={() => router.push(NEED_HREF)}
    />
  );

  return (
    <WorkspacePage title={TITLE} withThread card={card}>
      <div className={styles.canvas}>
        <CriteriaSummary
          age={ageLabel}
          district={district}
          needs={needs.map(needLabel)}
          urgency={urgencyLabel}
        />
        <section className={styles.panel} aria-label="Matching service groups and services">
          {chosen === null ? (
            <h2 className={styles.heading}>Services</h2>
          ) : (
            <h2 className={styles.heading}>
              <button
                type="button"
                className={styles.returnButton}
                aria-label="Return to service groups"
                onClick={() => router.push(workspaceHref('advisor.results', { order }))}
              >
                {chosen.label}
              </button>
            </h2>
          )}
          <p className={styles.note} role="status">
            {status}
          </p>
          {onResults && current?.kind === 'failed' ? (
            <p className={styles.failed} role="alert">
              {FAILED}
            </p>
          ) : null}
          {onResults && notFound ? <p className={styles.note}>{NOT_PLACED}</p> : null}
          {onResults && read !== null && groups.length === 0 ? <p className={styles.note}>{NONE}</p> : null}
          {onResults && read !== null && groups.length > 0 && chosen === null ? (
            <PagedGrid
              items={groups}
              keyOf={(item) => item.category}
              label="Service groups"
              noun="service groups"
              empty="No service groups."
              render={(item) => (
                <button
                  type="button"
                  className={styles.groupCard}
                  data-el="ADV2-GROUP"
                  onClick={() => router.push(workspaceHref('advisor.results', { group: item.category, order }))}
                >
                  <span className={styles.groupName}>{item.label}</span>
                  <span className={styles.pill}>
                    {`${item.services.length} of ${Math.max(item.services.length, totals[item.category] ?? 0)} services`}
                  </span>
                </button>
              )}
            />
          ) : null}
          {chosen === null ? null : (
            <>
              <div className={styles.toolbar}>
                <p className={styles.note}>
                  {order === 'travel' ? 'Listed by travel time. Not ranked by status.' : 'Listed by name. Not ranked by status.'}
                </p>
                <div className={styles.orderSeg} role="group" aria-label="List by">
                  <button
                    type="button"
                    className={styles.seg}
                    aria-pressed={order === 'travel'}
                    onClick={() => router.push(workspaceHref('advisor.results', { group: chosen.category, order: 'travel' }))}
                  >
                    Travel time
                  </button>
                  <button
                    type="button"
                    className={styles.seg}
                    aria-pressed={order === 'name'}
                    onClick={() => router.push(workspaceHref('advisor.results', { group: chosen.category, order: 'name' }))}
                  >
                    Name
                  </button>
                </div>
              </div>
              <PagedGrid
                items={orderServices(chosen.services, order)}
                keyOf={(item) => item.serviceId}
                label="Services in this group"
                noun="services"
                empty="No services."
                render={(item) => (
                  <div onClickCapture={() => remember(openedOf(item))}>
                    <ServiceTile option={toOption(item)} />
                  </div>
                )}
              />
            </>
          )}
        </section>
      </div>
    </WorkspacePage>
  );
}
