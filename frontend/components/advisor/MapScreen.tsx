'use client';

import Link from 'next/link';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { bffFetch } from '@/lib/advisor/browser';
import { AGE_BANDS, labelOf, NEEDS, URGENCIES, type CaseView } from '@/lib/advisor/codes';
import { chooseDistrict } from '@/lib/advisor/district';
import { canChangePostcode, changePostcode, type PostcodeChange } from '@/lib/advisor/postcodeChange';
import type { OptionsParts, OptionView } from '@/lib/advisor/options';
import { durationText } from '@/lib/board/format';
import { Button } from '@/components/ui/Button';
import { MapLoadingBox } from '@/components/map/MapLoadingBox';
import { useMapPreload } from '@/components/map/TileMap';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import { AskClinicalPanel } from './AskClinicalPanel';
import { OptionsMap } from './OptionsMap';
import { OutOfArea } from './PostcodeStates';
import { numberText } from './ServiceCard';
import { ViewToggle } from './ViewToggle';
import styles from './MapScreen.module.css';

// The map view of the options (W50, Map and MapLost boards). It reads the same options as the list, once per
// load, and the case for its postcode. The map sits beside the same services as a list (above it on a phone).
// A postcode that is not found gets its own card, with a field to type it again and the districts the services
// cover to choose from; a district chosen is saved on the case and the options are read again (W9H, DEC-1045).
// A postcode outside the area keeps the shared state.

type Load =
  | { kind: 'loading' }
  | { kind: 'ready'; parts: OptionsParts; postcode: string | null; view: CaseView | null }
  | { kind: 'failed' };

const CHOICE_FAILED = 'We could not use that district. Try again, or choose another.';
const POSTCODE_HINT = 'Enter a full postcode, for example DT4 8XX.';
const SEARCH_MESSAGES: Record<Exclude<PostcodeChange, 'saved'>, string> = {
  invalid: POSTCODE_HINT,
  conflict: 'The case changed while you were typing. Read it again, then try again.',
  failed: 'The postcode could not be tried. Try again.',
};

// "80+ · DT4 8XX · Frailty · Within 2 hrs": who the options are for, in one line, never a name.
function summaryOf(view: CaseView | null, postcode: string | null): string {
  const needs = (view?.needs ?? []).map((code) => NEEDS.find((need) => need.code === code)?.short ?? code);
  return [labelOf(AGE_BANDS, view?.ageBand ?? null), postcode, needs.length === 0 ? null : needs.join(', '), labelOf(URGENCIES, view?.urgency ?? null)]
    .filter((part): part is string => part !== null && part !== '')
    .join(' · ');
}

// The line under a service's name: the travel, and when the figure was reported.
function sideLine(option: OptionView) {
  const travel =
    option.travel !== null
      ? `${option.travel.low === option.travel.high ? option.travel.low : `${option.travel.low} to ${option.travel.high}`} min by road`
      : (option.travelText ?? (option.coverage !== null ? 'Visits the patient' : null));
  const age = option.dataAgeSeconds === null ? null : `${durationText(Math.floor(option.dataAgeSeconds / 60))} ago`;
  return (
    <>
      {[travel, option.staleWarning ? null : age].filter((part) => part !== null).join(' · ')}
      {option.staleWarning && age !== null ? (
        <>
          {travel === null ? '' : ' · '}
          <strong className={styles.old}>{`${age} · old`}</strong>
        </>
      ) : null}
    </>
  );
}

function SideCard({ option, caseId, selected }: { option: OptionView; caseId: string; selected: boolean }) {
  const figure = numberText(option);
  const chip = figure === '?' ? STATUS_LABELS[option.status] : `${STATUS_LABELS[option.status]} · ${figure}`;
  return (
    <article className={styles.item} aria-label={option.name} data-status={option.status} data-selected={selected} data-el="ADV-MAP-ITEM">
      <h3 className={styles.itemName}>{option.name}</h3>
      {option.network === null ? null : <p className={styles.itemLine}>{option.network.organisation}</p>}
      <p className={styles.itemLine}>{sideLine(option)}</p>
      <div className={styles.itemFoot}>
        <span className={styles.chip}>
          <ShapeIcon shape={STATUS_SHAPES[option.status]} />
          {chip}
        </span>
        <Link
          className={styles.open}
          href={`/advisor/case/${encodeURIComponent(caseId)}/options?service=${encodeURIComponent(option.serviceId)}`}
          aria-label={`Open ${option.name}`}
          data-el="ADV-MAP-OPEN-LINK"
        >
          Open
        </Link>
      </div>
    </article>
  );
}

type LostProps = {
  caseId: string;
  postcode: string | null;
  districts: string[];
  onAskClinical: () => void;
  onChooseDistrict: (district: string) => Promise<boolean>;
  onSearchAgain?: (postcode: string) => Promise<PostcodeChange>;
};

// The postcode-not-found card (MapLost): the postcode to mend, the districts to choose, the one primary action.
// Nothing about the case changes until the advisor saves a postcode or presses "Use district".
function PostcodeLost({ caseId, postcode, districts, onAskClinical, onChooseDistrict, onSearchAgain }: LostProps) {
  const ids = useId();
  const [typed, setTyped] = useState(postcode ?? '');
  const [searching, setSearching] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [using, setUsing] = useState(false);
  const [failed, setFailed] = useState(false);
  const canSearch = onSearchAgain !== undefined;
  const canChoose = districts.length > 0;

  const search = async () => {
    if (searching || onSearchAgain === undefined) return;
    setSearching(true);
    setProblem(null);
    const result = await onSearchAgain(typed);
    // Kept: the screen changes with the new options. Not kept: say so, in words, beside the field.
    if (result !== 'saved') {
      setProblem(SEARCH_MESSAGES[result]);
      setSearching(false);
    }
  };

  const use = async () => {
    if (chosen === null || using) return;
    setUsing(true);
    setFailed(false);
    const kept = await onChooseDistrict(chosen);
    if (!kept) {
      setFailed(true);
      setUsing(false);
    }
  };

  const lead = [
    'The map needs a place to start from.',
    canSearch && canChoose
      ? 'Check the postcode, or choose the district the patient is in.'
      : canChoose
        ? 'Choose the district the patient is in.'
        : canSearch
          ? 'Check the postcode.'
          : 'Check the postcode with the caller.',
    canSearch || canChoose ? 'Nothing else about the case changes.' : null,
  ]
    .filter((part) => part !== null)
    .join(' ');

  return (
    <section className={styles.lost} aria-labelledby={`${ids}-title`}>
      <div>
        <h1 id={`${ids}-title`} className={styles.lostTitle}>
          We could not place that postcode in your area
        </h1>
        <p className={styles.lostLead}>{lead}</p>
      </div>

      {canSearch ? (
        <div>
          <label htmlFor={`${ids}-postcode`} className={styles.fieldLabel}>
            Postcode
          </label>
          <div className={styles.search}>
            <input
              id={`${ids}-postcode`}
              type="text"
              className={styles.field}
              value={typed}
              autoComplete="off"
              aria-invalid={problem === null ? undefined : true}
              aria-describedby={`${ids}-hint`}
              onChange={(event) => setTyped(event.target.value)}
              data-el="ADV-POSTCODE-FIX"
            />
            <Button variant="secondary" busy={searching} onClick={() => void search()} dataEl="ADV-POSTCODE-SEARCH-BTN">
              Search again
            </Button>
          </div>
          <p key={problem === null ? 'hint' : 'problem'} id={`${ids}-hint`} className={styles.hint} role={problem === null ? undefined : 'alert'}>
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M12 3.5L21.5 20h-19z" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
              <path d="M12 9.5v4.5M12 16.8v.1" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
            </svg>
            {problem ?? POSTCODE_HINT}
          </p>
        </div>
      ) : null}

      {canChoose ? (
        <div>
          <p id={`${ids}-districts`} className={styles.districtTitle}>
            {canSearch ? 'Or choose' : 'Choose'} a district the services cover
          </p>
          <p className={styles.districtNote}>These are the districts at least one service covers.</p>
          <div role="group" aria-labelledby={`${ids}-districts`} className={styles.chips}>
            {districts.map((district) => (
              <button
                key={district}
                type="button"
                className={styles.opt}
                aria-pressed={chosen === district}
                disabled={using}
                onClick={() => setChosen(district)}
                data-el={`ADV-DISTRICT-${district}`}
              >
                {district}
              </button>
            ))}
          </div>
          {using ? (
            <p role="status" className={styles.status}>{`Using ${chosen}.`}</p>
          ) : null}
          {failed ? (
            <p role="alert" className={styles.problem}>
              {CHOICE_FAILED}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className={styles.lostFoot}>
        {canChoose ? (
          <button type="button" className={styles.use} disabled={chosen === null || using} onClick={() => void use()} data-el="ADV-DISTRICT-USE-BTN">
            {chosen === null ? 'Use district' : `Use district ${chosen}`}
          </button>
        ) : null}
        <Link className={styles.back} href={`/advisor/case/${encodeURIComponent(caseId)}/options`}>
          Back to the list
        </Link>
        <Button variant="secondary" dataEl="ADV-NOFIT-CLINICAL-BTN" onClick={onAskClinical}>
          Ask a clinical advisor
        </Button>
        {canChoose ? <p className={styles.lostSaved}>The district is saved on the case and the options are read again.</p> : null}
      </div>
    </section>
  );
}

export function MapScreen({ caseId, initialCoverage = false }: { caseId: string; initialCoverage?: boolean }) {
  useMapPreload();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const requested = useRef<string | null>(null);
  const id = encodeURIComponent(caseId);

  const read = useCallback(async () => {
    const [options, caseRead] = await Promise.all([
      bffFetch<OptionsParts>(`/api/bff/cases/${id}/options`),
      bffFetch<CaseView>(`/api/bff/cases/${id}`),
    ]);
    if (!options.ok) {
      setLoad({ kind: 'failed' });
      return;
    }
    setLoad({ kind: 'ready', parts: options.body, postcode: caseRead.ok ? caseRead.body.postcode : null, view: caseRead.ok ? caseRead.body : null });
  }, [id]);

  useEffect(() => {
    if (requested.current === caseId) return;
    requested.current = caseId;
    void read();
  }, [caseId, read]);

  // Saves the district chosen and, once it is kept, runs the options again for it.
  const choose = async (district: string): Promise<boolean> => {
    if (!(await chooseDistrict(caseId, district))) return false;
    await read();
    return true;
  };

  // The postcode typed again from the not-found state: kept, the options are read again for it (MapWeb 3).
  const searchAgain = async (typed: string): Promise<PostcodeChange> => {
    if (load.kind !== 'ready' || load.view === null) return 'failed';
    const result = await changePostcode(load.view, typed);
    if (result === 'saved') await read();
    return result;
  };

  if (load.kind === 'loading') {
    return <MapLoadingBox />;
  }
  if (load.kind === 'failed') return <p role="alert">The map could not be read. Try again.</p>;

  const { parts, postcode, view } = load;
  // "Ask a clinical advisor" (W45): a postcode the map cannot place is one of the states that offers it.
  const ask = asking ? <AskClinicalPanel caseRef={caseId} optionsShown={0} onClose={() => setAsking(false)} /> : null;
  if (parts.notFound) {
    return (
      <>
        <PostcodeLost
          caseId={caseId}
          postcode={postcode}
          districts={parts.districts ?? []}
          onAskClinical={() => setAsking(true)}
          onChooseDistrict={choose}
          onSearchAgain={canChangePostcode(view) ? searchAgain : undefined}
        />
        {ask}
      </>
    );
  }
  if (parts.outOfArea) {
    return (
      <>
        <OutOfArea caseId={caseId} postcode={postcode ?? 'This postcode'} onAskClinical={() => setAsking(true)} districts={parts.districts} onChooseDistrict={choose} />
        {ask}
      </>
    );
  }

  const place = postcode ?? 'this patient';
  const summary = summaryOf(view, postcode);
  return (
    <section className={styles.screen} aria-label="Options on a map">
      <h1 className={styles.visuallyHidden}>{`Options near ${place}`}</h1>
      <div className={styles.bar}>
        <ViewToggle caseId={caseId} current="map" />
        {summary === '' ? null : (
          <p className={styles.summary} data-el="ADV-MAP-SUMMARY">
            {summary}
          </p>
        )}
      </div>
      <div className={styles.board}>
        <OptionsMap
          caseId={caseId}
          postcode={place}
          patientArea={parts.patientArea}
          options={parts.options}
          selectedId={selected}
          onSelect={(serviceId) => setSelected(serviceId)}
          initialCoverage={initialCoverage}
        />
        <section className={styles.side} aria-label="The same services as a list">
          <p className={styles.sideNote}>Same services as the list. Sorted by travel time. Not ranked.</p>
          <p className={styles.sideNote} data-el="ADV-MAP-COUNT">{`${parts.options.length} ${parts.options.length === 1 ? 'service' : 'services'} shown`}</p>
          {parts.options.map((option) => (
            <SideCard key={option.serviceId} option={option} caseId={caseId} selected={option.serviceId === selected} />
          ))}
        </section>
      </div>
    </section>
  );
}
