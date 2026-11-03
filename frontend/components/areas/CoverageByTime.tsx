'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { bffGet } from '@/lib/bff/client';
import { type CoverageView, type DistrictCover, parseCoverage, summariseCoverage, WINDOWS, type WindowCode } from '@/lib/areas/types';
import styles from './coverage.module.css';

// Where coverage runs out (RadarWeb 4): for each postcode district, which visiting services cover it in the
// chosen part of the day, the districts with no cover, the districts with two or more, and the referrals that
// came from uncovered districts. For the lead, the ICB and the COO. The districts are tiles, not shapes on a
// map: the back end holds no district outlines, and a drawn outline would be a guess. A count under 10 is
// withheld by the back end and read as "Fewer than 10", never as zero (DEC-393). A tile opens to say who covers
// its district; the back end gives services only, not the hours each one covers, so the card does not give hours.

const NOTE = 'Coverage is by postcode district. Demand comes from the decision log. Groups under 10 are hidden.';
const OPEN_HINT = 'Open a tile to see who covers it. It does not change what either service accepts.';

type State = { key: WindowCode; kind: 'ok'; view: CoverageView } | { key: WindowCode; kind: 'failed' };

function labelOf(window: WindowCode): string {
  return WINDOWS.find((item) => item.value === window)?.label ?? '';
}

/** "A", "A and B", "A, B and C": the words for a list. */
function listWords(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

function listText(districts: string[]): string {
  return districts.length === 0 ? 'None' : districts.join(', ');
}

function tileState(services: string[]): { word: string; mark: string } {
  if (services.length === 0) return { word: 'No cover', mark: 'none' };
  return services.length === 1 ? { word: 'One service', mark: 'one' } : { word: 'Two or more', mark: 'many' };
}

function coverSentence(entry: DistrictCover, when: string): string {
  if (entry.services.length === 0) return `No visiting service covers ${entry.district} ${when}.`;
  return `Covered by ${listWords(entry.services)} ${when}.`;
}

export function CoverageByTime() {
  const [part, setPart] = useState<WindowCode>('all');
  const [state, setState] = useState<State | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    void bffGet(`/api/bff/planning/coverage?window=${part}`, (value) => {
      const view = parseCoverage(value);
      if (view === null) throw new Error('shape');
      return view;
    }).then((result) => {
      if (!current) return;
      setState(result.ok ? { key: part, kind: 'ok', view: result.data } : { key: part, kind: 'failed' });
    });
    return () => {
      current = false;
    };
  }, [part, attempt]);

  // The answer on screen is the one for the window chosen; while another is on its way the screen says so.
  const settled = state !== null && state.key === part ? state : null;

  return (
    <section className={styles.analysis} aria-label="Coverage by time of day">
      <h1 className={styles.heading}>Coverage by time of day</h1>
      <p className={styles.sub}>For leads, the ICB and the COO.</p>

      <fieldset className={styles.chips}>
        <legend className={styles.legend}>Time of day</legend>
        {WINDOWS.map((item) => (
          <Chip key={item.value} pressed={part === item.value} onPressedChange={() => setPart(item.value)} dataEl={`COV-WINDOW-${item.value.toUpperCase()}`}>
            {item.label}
          </Chip>
        ))}
      </fieldset>

      {settled === null ? (
        <p role="status">Loading the coverage.</p>
      ) : settled.kind === 'failed' ? (
        <div>
          <p role="alert">Coverage by time of day could not be loaded. Try again.</p>
          <div className={styles.actions}>
            <Button variant="secondary" onClick={() => { setState(null); setAttempt((n) => n + 1); }} dataEl="COV-RETRY-BTN">
              Try again
            </Button>
          </div>
        </div>
      ) : settled.view.districts.length === 0 ? (
        <p role="status">No districts are listed for this part of the day.</p>
      ) : (
        <Body view={settled.view} />
      )}

      <p className={styles.note}>{NOTE}</p>
      <div className={styles.actions}>
        <Button variant="secondary" href="/planning/flows" dataEl="COV-PLANNING-BTN">
          Open planning view
        </Button>
      </div>
    </section>
  );
}

function Body({ view }: { view: CoverageView }) {
  const [opened, setOpened] = useState<string | null>(null);
  const { none, twoOrMore } = summariseCoverage(view);
  const { uncovered } = view;
  const current = view.districts.find((entry) => entry.district === opened);
  const when = view.window === 'all' ? 'all day' : `between ${labelOf(view.window).replace(' to ', ' and ')}`;
  return (
    <div className={styles.body}>
      <div className={styles.card}>
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>Which visiting services cover each district</h2>
          <div className={styles.key}>
            <span className={styles.keyItem}>
              <i className={styles.swatch} data-cover="none" aria-hidden="true" />
              No cover
            </span>
            <span className={styles.keyItem}>
              <i className={styles.swatch} data-cover="one" aria-hidden="true" />
              One service
            </span>
            <span className={styles.keyItem}>
              <i className={styles.swatch} data-cover="many" aria-hidden="true" />
              Two or more
            </span>
          </div>
        </div>
        <ul className={styles.tiles} aria-label="Districts and who covers them" data-el="COV-TILES">
          {view.districts.map((entry) => {
            const tile = tileState(entry.services);
            return (
              <li key={entry.district} className={styles.tile} data-cover={tile.mark}>
                <button
                  type="button"
                  className={styles.tileButton}
                  aria-pressed={entry.district === opened}
                  onClick={() => setOpened(entry.district)}
                  data-el={`COV-TILE-${entry.district}`}
                >
                  <strong className={styles.district}>{entry.district}</strong>
                  <span className={styles.cover}>{tile.word}</span>
                  <span className={styles.services}>{entry.services.length === 0 ? 'No visiting service' : entry.services.join(', ')}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <p className={styles.note}>Districts are shown as tiles, not on a map.</p>
      </div>

      <div className={styles.side}>
        <div className={styles.card}>
          <p className={styles.eyebrow}>{view.window === 'all' ? 'All day' : `In ${labelOf(view.window)}`}</p>
          <dl className={styles.facts}>
            <div>
              <dt>Areas with no visiting service</dt>
              <dd data-el="COV-NONE">{listText(none)}</dd>
            </div>
            <div>
              <dt>Areas with two or more</dt>
              <dd data-el="COV-MANY">{listText(twoOrMore)}</dd>
            </div>
            <div>
              <dt>{`Referrals from uncovered areas, last ${uncovered.days} days`}</dt>
              <dd data-el="COV-REFERRALS">{uncovered.suppressed || uncovered.count === null ? 'Fewer than 10' : String(uncovered.count)}</dd>
            </div>
          </dl>
        </div>

        <section className={`${styles.card} ${styles.detail}`} aria-live="polite">
          {current === undefined ? null : (
            <>
              <p className={styles.eyebrow}>{`${current.district} · opened`}</p>
              <p className={styles.detailText}>{coverSentence(current, when)}</p>
            </>
          )}
          <p className={styles.hint}>{OPEN_HINT}</p>
        </section>
      </div>
    </div>
  );
}
