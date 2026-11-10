'use client';

import { useEffect, useState } from 'react';
import { AGE_BANDS, NEEDS, URGENCIES, type AgeCode, type NeedCode, type UrgencyCode } from '@/lib/advisor/codes';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { locatePostcode, type PostcodeLocation, suggestPostcodes } from '@/lib/advisor/postcodeSuggest';
import { findServices } from '@/lib/advisor/v2/browser';
import { groupsOf, orderServices, toOption, type FindRead, type ServiceOrder } from '@/lib/advisor/v2/find';
import { V2_BROWSE_NOTE } from '@/lib/advisor/v2/overview';
import { PostcodePicker } from '../advisor/PostcodePicker';
import { PagedGrid, ServiceTile } from './parts';
import styles from './V2.module.css';

// Find a Service (DEC-1366), in the layout of the SPoA design: the patient criteria on the left (four quick steps on a
// narrow screen), the matching service groups on the right, and a group opens to its services. There is no Find
// button: the results follow the criteria, and a search runs only when the postcode is a full one and the age, need
// and time are chosen, so a half-typed postcode is never sent. Services are listed by travel time or name, never
// ranked by status. Browse only: this opens no case and nothing is stored. The postcode lives only in this form.

type Step = 'age' | 'postcode' | 'need' | 'urgency';
type Result = { kind: 'idle' } | { kind: 'searching' } | { kind: 'failed' } | { kind: 'done'; read: FindRead };

const STEPS: readonly (readonly [Step, string])[] = [
  ['age', 'Age'],
  ['postcode', 'Postcode'],
  ['need', 'Need'],
  ['urgency', 'Time'],
];
const POSTCODE_HELP = 'Enter a full postcode, for example DT4 8XX.';
const WAIT_MS = 250;
const POSTCODE_ID = 'v2-postcode';
const POSTCODE_LIST_ID = 'v2-postcode-suggestions';

export function FindService() {
  const [postcode, setPostcode] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [located, setLocated] = useState<PostcodeLocation | null>(null);
  const [age, setAge] = useState<AgeCode | null>(null);
  const [needs, setNeeds] = useState<NeedCode[]>([]);
  const [urgency, setUrgency] = useState<UrgencyCode | null>(null);
  const [step, setStep] = useState<Step>('age');
  const [searched, setResult] = useState<Result>({ kind: 'idle' });
  const [group, setGroup] = useState<string | null>(null);
  const [order, setOrder] = useState<ServiceOrder>('travel');

  const full = normalisePostcode(postcode);
  const needsKey = [...needs].sort().join(',');
  const ready = full !== null && age !== null && needs.length > 0 && urgency !== null;
  // Incomplete criteria show nothing, whatever the last search found.
  const result: Result = ready ? searched : { kind: 'idle' };
  const active = postcode.trim() !== '' || age !== null || needs.length > 0 || urgency !== null;

  useEffect(() => {
    if (full === null || age === null || needs.length === 0 || urgency === null) return;
    let live = true;
    const timer = setTimeout(() => {
      setResult({ kind: 'searching' });
      findServices({ postcode: full, ageBand: age, needs, urgency }).then((read) => {
        if (live) setResult(read === null ? { kind: 'failed' } : { kind: 'done', read });
      });
    }, WAIT_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // `needs` is compared by its sorted key: a new array with the same needs is not a new search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [full, age, needsKey, urgency]);

  const toggleNeed = (code: NeedCode) =>
    setNeeds((current) => (current.includes(code) ? current.filter((item) => item !== code) : [...current, code]));

  // The same postcode lookup as the advisor's needs form (DEC-1332, DEC-1340): suggestions as the postcode is typed and
  // the position of a full one. A lookup that cannot answer never blocks the search, which uses the postcode as typed.
  function onPostcodeBlur() {
    const normal = normalisePostcode(postcode);
    if (normal === null) return setLocated(null);
    setPostcode(normal);
    void locatePostcode(normal).then(setLocated);
  }

  function reset() {
    setPostcode('');
    setSuggestions([]);
    setLocated(null);
    setAge(null);
    setNeeds([]);
    setUrgency(null);
    setGroup(null);
    setStep('age');
  }

  const groups = result.kind === 'done' ? groupsOf(result.read.services) : [];
  const chosen = groups.find((item) => item.category === group) ?? null;
  const total = result.kind === 'done' ? result.read.services.length : 0;

  let status = 'Choose the postcode, age, need and time to list services.';
  if (ready && result.kind === 'searching') status = 'Searching.';
  if (result.kind === 'done') {
    status = chosen === null ? `${groups.length} service groups · ${total} services` : `${chosen.services.length} matching services`;
  }

  const postcodeHelp = full !== null ? 'Postcode accepted.' : POSTCODE_HELP;

  return (
    <div className={styles.app}>
      <div className={styles.finderLayout}>
        <form className={`${styles.panel} ${styles.filters}`} autoComplete="off" onSubmit={(event) => event.preventDefault()} aria-labelledby="v2-criteria">
          <h2 id="v2-criteria">Patient criteria</h2>
          <div className={styles.steps} role="tablist" aria-label="Quick filter categories">
            {STEPS.map(([id, label]) => (
              <button key={id} type="button" role="tab" className={styles.seg} aria-selected={step === id} onClick={() => setStep(id)}>
                {label}
              </button>
            ))}
          </div>
          <div className={styles.fields} data-step={step}>
            <fieldset className={`${styles.field} ${styles.fieldAge}`}>
              <legend>Patient age</legend>
              <div className={styles.choices}>
                {AGE_BANDS.map((band) => (
                  <button key={band.code} type="button" className={styles.choice} aria-pressed={age === band.code} onClick={() => setAge(band.code)}>
                    {band.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <div className={`${styles.field} ${styles.fieldPostcode}`}>
              <label htmlFor="v2-postcode">Postcode</label>
              <PostcodePicker
                id={POSTCODE_ID}
                listId={POSTCODE_LIST_ID}
                value={postcode}
                options={suggestions}
                invalid={false}
                describedBy="v2-postcode-help"
                dataEl="ADV-V2-POSTCODE"
                onType={(typed) => {
                  setPostcode(typed);
                  setLocated(null);
                  void suggestPostcodes(typed).then(setSuggestions);
                }}
                onPick={(picked) => {
                  setPostcode(picked);
                  setSuggestions([]);
                  setLocated(null);
                  void locatePostcode(picked).then(setLocated);
                }}
                onBlur={onPostcodeBlur}
              />
              <p id="v2-postcode-help" className={styles.help} aria-live="polite" data-el="ADV-V2-POSTCODE-LOOKUP">
                {located === null
                  ? postcodeHelp
                  : located.status === 'found'
                    ? `Found: ${located.lat.toFixed(5)}, ${located.lon.toFixed(5)} (OS Places).`
                    : located.status === 'not-found'
                      ? 'Not found. Check the postcode.'
                      : 'The postcode lookup is unavailable. The search still uses the postcode as typed.'}
              </p>
            </div>
            <fieldset className={`${styles.field} ${styles.fieldNeed}`}>
              <legend>Patient need</legend>
              <div className={styles.choices}>
                {NEEDS.map((need) => (
                  <button key={need.code} type="button" className={styles.choice} aria-pressed={needs.includes(need.code)} onClick={() => toggleNeed(need.code)}>
                    {need.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset className={`${styles.field} ${styles.fieldUrgency}`}>
              <legend>Required timeframe</legend>
              <div className={styles.choices}>
                {URGENCIES.map((item) => (
                  <button key={item.code} type="button" className={styles.choice} aria-pressed={urgency === item.code} onClick={() => setUrgency(item.code)}>
                    {item.label}
                  </button>
                ))}
              </div>
            </fieldset>
          </div>
          <button type="button" className={styles.reset} onClick={reset} disabled={!active}>
            Reset filters
          </button>
        </form>

        <section className={`${styles.panel} ${styles.results}`} aria-label="Matching service groups and services">
          {chosen === null ? (
            <h2>Services</h2>
          ) : (
            <h2>
              <button type="button" className={styles.returnButton} aria-label="Return to service groups" onClick={() => setGroup(null)}>
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="m11 17-5-5 5-5M6 12h12" />
                </svg>
                <span>{chosen.label}</span>
              </button>
            </h2>
          )}
          <p className={styles.note} role="status">
            {status}
          </p>
          {result.kind === 'failed' ? (
            <p className={styles.failed} role="alert">
              The services could not be searched. Change a choice to try again, or phone the services.
            </p>
          ) : null}
          {result.kind === 'done' && result.read.notFound ? (
            <p className={styles.note}>The postcode could not be placed, so no travel time is shown. Services are listed by name.</p>
          ) : null}
          {result.kind === 'done' && groups.length === 0 ? (
            <p className={styles.note}>No service takes this patient on its criteria. Phone to confirm, or change the criteria.</p>
          ) : null}
          {result.kind === 'done' && groups.length > 0 && chosen === null ? (
            <PagedGrid
              items={groups}
              keyOf={(item) => item.category}
              label="Service groups"
              noun="service groups"
              empty="No service groups."
              render={(item) => (
                <button type="button" className={styles.groupCard} onClick={() => setGroup(item.category)} data-el="ADV2-GROUP">
                  <span className={styles.itemText}>
                    <strong>{item.label}</strong>
                  </span>
                  <span className={styles.pill}>{`${item.services.length} of ${Math.max(item.services.length, result.read.groupTotals[item.category] ?? 0)} services`}</span>
                </button>
              )}
            />
          ) : null}
          {chosen === null ? null : (
            <>
              <div className={styles.toolbar}>
                <p className={styles.note}>{order === 'travel' ? 'Listed by travel time. Not ranked by status.' : 'Listed by name. Not ranked by status.'}</p>
                <div className={styles.orderSeg} role="group" aria-label="List by">
                  <button type="button" className={styles.seg} aria-pressed={order === 'travel'} onClick={() => setOrder('travel')}>
                    Travel time
                  </button>
                  <button type="button" className={styles.seg} aria-pressed={order === 'name'} onClick={() => setOrder('name')}>
                    Name
                  </button>
                </div>
              </div>
              <PagedGrid
                items={orderServices(chosen.services, order).map(toOption)}
                keyOf={(item) => item.serviceId}
                label="Services in this group"
                noun="services"
                empty="No services."
                render={(item) => <ServiceTile option={item} />}
              />
            </>
          )}
        </section>
      </div>
      <p className={styles.footer}>{V2_BROWSE_NOTE}</p>
    </div>
  );
}
