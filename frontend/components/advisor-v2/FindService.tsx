'use client';

import { type FormEvent, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { AGE_BANDS, NEEDS, URGENCIES, type AgeCode, type NeedCode, type UrgencyCode } from '@/lib/advisor/codes';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { locatePostcode, type PostcodeLocation, suggestPostcodes } from '@/lib/advisor/postcodeSuggest';
import { findServices } from '@/lib/advisor/v2/browser';
import { groupsOf, orderServices, toOption, type FindRead, type ServiceOrder } from '@/lib/advisor/v2/find';
import { V2_BROWSE_NOTE } from '@/lib/advisor/v2/overview';
import { PostcodePicker } from '../advisor/PostcodePicker';
import { ServiceRows } from './ServiceRows';
import styles from './V2.module.css';

// Find a Service (DEC-1366): the postcode, age band, need and how soon, then a card for each service group that has
// a service whose criteria take this patient, then the services of the chosen group in travel-time or name order,
// never ranked by status. Browse only: this opens no case and nothing is stored. The postcode is sent once, in the
// body of the search, and lives only in this form; it is never in the address or in browser storage.

type Result = { kind: 'idle' } | { kind: 'searching' } | { kind: 'failed' } | { kind: 'done'; read: FindRead };

const POSTCODE_HELP = 'Enter a full postcode, for example DT4 8XX.';
const POSTCODE_ID = 'v2-postcode';
const POSTCODE_LIST_ID = 'v2-postcode-suggestions';

export function FindService() {
  const [postcode, setPostcode] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [located, setLocated] = useState<PostcodeLocation | null>(null);
  const [age, setAge] = useState<AgeCode | null>(null);
  const [needs, setNeeds] = useState<NeedCode[]>([]);
  const [urgency, setUrgency] = useState<UrgencyCode | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<Result>({ kind: 'idle' });
  const [group, setGroup] = useState<string | null>(null);
  const [order, setOrder] = useState<ServiceOrder>('travel');

  const toggleNeed = (code: NeedCode) =>
    setNeeds((current) => (current.includes(code) ? current.filter((item) => item !== code) : [...current, code]));

  // The same postcode lookup as the advisor's needs form (DEC-1332, DEC-1340): suggestions as the postcode is typed,
  // and the position of a full one. A lookup that cannot answer never blocks the search.
  function onPostcodeBlur() {
    const normal = normalisePostcode(postcode);
    if (normal === null) return setLocated(null);
    setPostcode(normal);
    void locatePostcode(normal).then(setLocated);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const full = normalisePostcode(postcode);
    if (full === null) return setProblem(POSTCODE_HELP);
    if (age === null) return setProblem('Choose an age band.');
    if (needs.length === 0) return setProblem('Choose at least one need.');
    if (urgency === null) return setProblem('Choose how soon.');
    setProblem(null);
    setGroup(null);
    setResult({ kind: 'searching' });
    const read = await findServices({ postcode: full, ageBand: age, needs, urgency });
    setResult(read === null ? { kind: 'failed' } : { kind: 'done', read });
  }

  const groups = result.kind === 'done' ? groupsOf(result.read.services) : [];
  const chosen = groups.find((item) => item.category === group) ?? null;

  return (
    <div className={styles.page}>
      <p className={styles.note}>{V2_BROWSE_NOTE}</p>
      <form className={`${styles.card} ${styles.form}`} onSubmit={submit} noValidate>
        <div>
          <label className={styles.legend} htmlFor="v2-postcode">
            Postcode
          </label>
          <PostcodePicker
            id={POSTCODE_ID}
            listId={POSTCODE_LIST_ID}
            value={postcode}
            options={suggestions}
            invalid={problem === POSTCODE_HELP}
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
          <p id="v2-postcode-help" className={styles.small}>
            {POSTCODE_HELP}
          </p>
          {located !== null ? (
            <p className={styles.small} role="status" data-el="ADV-V2-POSTCODE-LOOKUP">
              {located.status === 'found'
                ? `Found: ${located.lat.toFixed(5)}, ${located.lon.toFixed(5)} (OS Places).`
                : located.status === 'not-found'
                  ? 'Not found. Check the postcode.'
                  : 'The postcode lookup is unavailable. The search still uses the postcode as typed.'}
            </p>
          ) : null}
        </div>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>Age band</legend>
          <div className={styles.choices}>
            {AGE_BANDS.map((band) => (
              <label key={band.code} className={styles.choice}>
                <input type="radio" name="v2-age" checked={age === band.code} onChange={() => setAge(band.code)} />
                {band.label}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>Need</legend>
          <div className={styles.choices}>
            {NEEDS.map((need) => (
              <label key={need.code} className={styles.choice}>
                <input type="checkbox" checked={needs.includes(need.code)} onChange={() => toggleNeed(need.code)} />
                {need.label}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>How soon</legend>
          <div className={styles.choices}>
            {URGENCIES.map((item) => (
              <label key={item.code} className={styles.choice}>
                <input type="radio" name="v2-urgency" checked={urgency === item.code} onChange={() => setUrgency(item.code)} />
                {item.label}
              </label>
            ))}
          </div>
        </fieldset>
        {problem === null ? null : (
          <p className={styles.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <Button variant="primary" type="submit" busy={result.kind === 'searching'} dataEl="ADV2-FIND-SUBMIT">
            Find services
          </Button>
        </div>
      </form>

      {result.kind === 'failed' ? (
        <p className={styles.failed} role="alert">
          The services could not be searched. Try again, or phone the services.
        </p>
      ) : null}

      {result.kind === 'done' ? (
        groups.length === 0 ? (
          <p className={styles.note} role="status">
            No service takes this patient on its criteria. Phone to confirm, or change the search.
          </p>
        ) : (
          <section aria-labelledby="v2-groups-heading" className={styles.page}>
            <h2 id="v2-groups-heading" className={styles.heading}>
              Service groups
            </h2>
            {result.read.notFound ? (
              <p className={styles.note}>The postcode could not be placed, so no travel time is shown. Services are listed by name.</p>
            ) : null}
            <ul className={styles.groups} aria-labelledby="v2-groups-heading">
              {groups.map((item) => (
                <li key={item.category}>
                  <button
                    type="button"
                    className={styles.groupButton}
                    aria-pressed={group === item.category}
                    onClick={() => setGroup(item.category)}
                    data-el="ADV2-GROUP"
                  >
                    <span className={styles.groupName}>{item.label}</span>
                    <span>{`${item.services.length} ${item.services.length === 1 ? 'service' : 'services'}`}</span>
                  </button>
                </li>
              ))}
            </ul>
            {chosen === null ? null : (
              <div className={styles.page}>
                <h2 className={styles.heading}>{chosen.label}</h2>
                <fieldset className={styles.group}>
                  <legend className={styles.legend}>List by</legend>
                  <div className={styles.choices}>
                    <label className={styles.choice}>
                      <input type="radio" name="v2-order" checked={order === 'travel'} onChange={() => setOrder('travel')} />
                      Travel time
                    </label>
                    <label className={styles.choice}>
                      <input type="radio" name="v2-order" checked={order === 'name'} onChange={() => setOrder('name')} />
                      Name
                    </label>
                  </div>
                </fieldset>
                <p className={styles.note}>{order === 'travel' ? 'Listed by travel time. Not ranked by status.' : 'Listed by name. Not ranked by status.'}</p>
                <ServiceRows label="Services in this group" options={orderServices(chosen.services, order).map(toOption)} />
              </div>
            )}
          </section>
        )
      ) : null}
    </div>
  );
}
