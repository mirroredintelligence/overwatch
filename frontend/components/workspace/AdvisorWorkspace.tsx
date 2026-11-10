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
  const { view, step, order } = url;

  const [result, setResult] = useState<Search | null>(null);
  const [located, setLocated] = useState<PostcodeLocation | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  // The last criteria a search was started for, so the same criteria are never searched twice.
  const lastKey = useRef<string | null>(null);

  // The list, the map and the reasons are the results views; the need step is the intake.
  const full = normalisePostcode(postcode);
  const district = full === null ? null : outwardCode(full);
  const ageLabel = AGE_BANDS.find((band) => band.code === age)?.label ?? null;
  const urgencyLabel = URGENCIES.find((item) => item.code === urgency)?.label ?? null;
  const ageOk = age !== null && full !== null;
  const onResults = view !== 'find' && criteriaComplete;
  const intakeStep: 'age' | 'need' = (view !== 'find' || step === 'need') && ageOk ? 'need' : 'age';

  // A results view without complete criteria, or the need step without an age and a full postcode, goes back to the intake.
  const needsGate = (view !== 'find' && !criteriaComplete) || (view === 'find' && step === 'need' && !ageOk);
  const gateTarget: string | null = needsGate ? (ageOk ? NEED_HREF : AGE_HREF) : null;

  // The key is what the search depends on.
  const needsKey = [...needs].sort().join(',');
  const searchKey = `${full ?? ''}|${age ?? ''}|${needsKey}|${urgency ?? ''}`;
  const current = result !== null && result.key === searchKey ? result : null;
  // The search runs on the need step once the criteria are complete. It also runs on a results view that has no answer
  // for the criteria: coming back from a service page mounts this page afresh, and the answer lived only in the page
  // before. The criteria are still in the provider, so the same search is made again (nothing is stored).
  const searching = criteriaComplete && ((view === 'find' && step === 'need') || (onResults && current === null));
  const read = current?.kind === 'done' ? current.read : null;
  const outcome: 'none' | 'failed' | 'done' = current === null || current.kind === 'searching' ? 'none' : current.kind;
  const count = read?.services.length ?? 0;
  const notSuitable = read?.notSuitable.length ?? 0;
  const notFound = read?.notFound === true;
  const listed = useMemo(() => (read === null ? [] : orderServices(read.services, order)), [read, order]);
  // The patient's place, from the postcode lookup the page already makes. It is held in memory only.
  const patient = located !== null && located.status === 'found' ? { lat: located.lat, lon: located.lon } : null;
  // The results are drawn when there is an answer with something to show; otherwise the panel says why not.
  const resultsShown = onResults && read !== null && (count > 0 || (view === 'why' && notSuitable > 0));

  const summaryLine =
    criteriaComplete && ageLabel !== null && district !== null && urgencyLabel !== null
      ? [ageLabel, district, needs.map(needLabel).join(', '), urgencyLabel].join(' · ')
      : null;

  let status = IDLE_STATUS;
  if (current?.kind === 'searching' || (searching && current === null)) status = SEARCHING;
  if (onResults && read !== null) status = `${count} matching services`;

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
        // Only the need step moves on to the results; a results view that searched again stays where it is.
        if (live && view === 'find') router.push(RESULTS_HREF);
      });
    }, WAIT_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // The criteria are compared by searchKey; the values read here are the ones of the render that changed it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searching, searchKey]);

  // The results turn (or the map or reasons turn): its counts, order and whether the search failed or the postcode could
  // not be placed. A failed search is the results turn, whichever view the person is on.
  const turn = outcome === 'failed' ? 'advisor.results' : view === 'map' ? 'advisor.map' : view === 'why' ? 'advisor.reasons' : 'advisor.results';
  useEffect(() => {
    if (!onResults || outcome === 'none') return;
    const context: DialogContext =
      outcome === 'failed'
        ? { failed: true, count: 0, order, summaryLine }
        : { count, notSuitable, order, summaryLine, ...(notFound ? { postcodeNotPlaced: true } : {}) };
    visit(turn, context);
  }, [visit, onResults, outcome, turn, count, notSuitable, notFound, order, summaryLine]);

  // A service chosen in the list or on the map is remembered for the thread, then its page opens.
  function openFromMap(service: FoundService) {
    remember(openedOf(service));
    router.push(serviceHref(service.serviceId));
  }

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

  // What the person is shown: the list, the list beside the map, or the services that were not suitable.
  const title = resultsShown && view === 'why' ? WHY_TITLE : TITLE;
  const backHref = onResults ? (view === 'list' ? NEED_HREF : RESULTS_HREF) : undefined;
  const heading =
    count === 1 ? "1 service meets this patient's criteria" : `${count} services meet this patient's criteria`;
  const sortNote = order === 'travel' ? 'Sorted by travel time. Not ranked.' : 'Listed by name. Not ranked.';

  const showAs = (
    <div className={styles.switch} role="group" aria-label="Show it as">
      <button type="button" className={styles.seg} aria-pressed={view === 'list'} onClick={() => router.push(workspaceHref('advisor.results', { order }))}>
        <span className={styles.tick} aria-hidden="true">
          ✓
        </span>
        List
      </button>
      <button type="button" className={styles.seg} aria-pressed={view === 'map'} onClick={() => router.push(workspaceHref('advisor.map', { order }))}>
        <span className={styles.tick} aria-hidden="true">
          ✓
        </span>
        List and map
      </button>
    </div>
  );

  let canvas: ReactElement;
  if (resultsShown && view === 'why' && read !== null) {
    canvas = (
      <div className={styles.results}>
        <NotSuitableList
          items={read.notSuitable}
          suitableCount={count}
          summaryLine={summaryLine}
          serviceHref={serviceHref}
          backHref={RESULTS_HREF}
        />
      </div>
    );
  } else if (resultsShown && view === 'map') {
    canvas = (
      <div className={styles.mapCanvas}>
        <section className={styles.mapList} aria-label="Service list">
          <div className={styles.mapHead}>
            <h1 className={styles.h1}>{count === 1 ? '1 service' : `${count} services`}</h1>
            {showAs}
          </div>
          <ResultsList services={listed} compact onOpen={(service) => remember(openedOf(service))} />
        </section>
        <section className={styles.mapCard} aria-label="Map">
          <p className={styles.note}>Same services as the list. {sortNote}</p>
          <div className={styles.mapBody}>
            <MapPane services={listed} patient={patient} onOpen={openFromMap} />
          </div>
        </section>
      </div>
    );
  } else if (resultsShown) {
    canvas = (
      <div className={styles.results}>
        <div className={styles.head}>
          <div className={styles.headText}>
            <h1 className={styles.h1}>{heading}</h1>
            <p className={styles.note}>{sortNote}</p>
            {notFound ? <p className={styles.note}>{NOT_PLACED}</p> : null}
          </div>
          {showAs}
        </div>
        <ResultsList services={listed} onOpen={(service) => remember(openedOf(service))} />
      </div>
    );
  } else {
    canvas = (
      <>
        {onResults ? null : (
          <CriteriaSummary age={ageLabel} district={district} needs={needs.map(needLabel)} urgency={urgencyLabel} />
        )}
        <section className={styles.panel} aria-label="Matching services">
          <h2 className={styles.heading}>Services</h2>
          <p className={styles.note} role="status">
            {status}
          </p>
          {onResults && current?.kind === 'failed' ? (
            <p className={styles.failed} role="alert">
              {FAILED}
            </p>
          ) : null}
          {onResults && notFound ? <p className={styles.note}>{NOT_PLACED}</p> : null}
          {onResults && read !== null && count === 0 ? <p className={styles.note}>{NONE}</p> : null}
        </section>
      </>
    );
  }

  return (
    <WorkspacePage title={title} backHref={backHref} withThread card={card}>
      <div className={styles.canvas}>{canvas}</div>
    </WorkspacePage>
  );
}
