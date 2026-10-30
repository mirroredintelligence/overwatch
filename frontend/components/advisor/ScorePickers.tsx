'use client';

import { useEffect, useState } from 'react';
import { Chip } from '@/components/ui/Chip';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffFetch } from '@/lib/advisor/browser';
import {
  type AcuityMethod,
  AMBULANCE_CATEGORIES,
  CFS_LABELS,
  CFS_MAX,
  CFS_MIN,
  MANCHESTER_TRIAGE,
  PATHWAYS_DEBOUNCE_MS,
  PATHWAYS_MIN_CHARACTERS,
  parseNews2,
  type Score,
} from '@/lib/advisor/scores';
import styles from './ScorePickers.module.css';

// The referrer's score row (W12): one picker per method, recorded as the referrer gave it. A method
// is chosen by its chip; "Not given" clears every method. The tool never calculates, infers or checks
// a score beyond its allowed range.

type DxItem = { code: string; display: string };
type Found = { query: string; items: DxItem[] };

const METHOD_CHIPS: readonly { method: AcuityMethod; label: string; id: string }[] = [
  { method: 'pathways-dx', label: 'NHS Pathways Dx', id: 'PATHWAYS' },
  { method: 'ambulance-category', label: 'Ambulance category', id: 'AMBULANCE' },
  { method: 'manchester', label: 'Manchester triage', id: 'MANCHESTER' },
  { method: 'news2', label: 'NEWS2', id: 'NEWS2' },
  { method: 'cfs', label: 'Frailty scale', id: 'CFS' },
];

export type ScorePickersProps = {
  value: Score[];
  onChange: (scores: Score[]) => void;
};

export function ScorePickers({ value, onChange }: ScorePickersProps) {
  const [methods, setMethods] = useState<AcuityMethod[]>(() => [...new Set(value.map((score) => score.method))]);
  const [notGiven, setNotGiven] = useState(false);

  const scoreFor = <M extends AcuityMethod>(method: M) =>
    value.find((score): score is Extract<Score, { method: M }> => score.method === method);

  // Replaces (or, with null, clears) the score of one method. Every other score is kept as it was.
  function setScore(method: AcuityMethod, score: Score | null) {
    const others = value.filter((item) => item.method !== method);
    onChange(score === null ? others : [...others, score]);
  }

  function toggleMethod(method: AcuityMethod, on: boolean) {
    if (on) {
      setMethods((current) => (current.includes(method) ? current : [...current, method]));
      setNotGiven(false);
      return;
    }
    setMethods((current) => current.filter((item) => item !== method));
    setScore(method, null);
  }

  function giveNone() {
    setMethods([]);
    setNotGiven(true);
    onChange([]);
  }

  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Score from the referrer (optional)</legend>
      <div className={styles.chips}>
        {METHOD_CHIPS.map((chip) => (
          <Chip
            key={chip.method}
            pressed={methods.includes(chip.method)}
            onPressedChange={(on) => toggleMethod(chip.method, on)}
            dataEl={`ADV-SCORE-${chip.id}-CHIP`}
          >
            {chip.label}
          </Chip>
        ))}
        <Chip pressed={notGiven} onPressedChange={(on) => (on ? giveNone() : setNotGiven(false))} dataEl="ADV-SCORE-NONE-CHIP">
          Not given
        </Chip>
      </div>

      {methods.includes('pathways-dx') ? (
        <PathwaysPicker
          chosen={scoreFor('pathways-dx')?.value ?? null}
          onChoose={(code) => setScore('pathways-dx', { method: 'pathways-dx', value: code })}
        />
      ) : null}

      {methods.includes('ambulance-category') ? (
        <section className={styles.picker} aria-label="Ambulance category">
          <h3 className={styles.heading}>Ambulance category</h3>
          <p className={styles.sub}>Used by 999</p>
          {AMBULANCE_CATEGORIES.map((category) => (
            <OptionButton
              key={category.value}
              selected={scoreFor('ambulance-category')?.value === category.value}
              onSelect={() => setScore('ambulance-category', { method: 'ambulance-category', value: category.value })}
              hint={category.hint}
              dataEl={`ADV-SCORE-AMBULANCE-${category.value}`}
            >
              {category.label}
            </OptionButton>
          ))}
          <p className={styles.note}>Recorded as the crew gave it.</p>
        </section>
      ) : null}

      {methods.includes('manchester') ? (
        <section className={styles.picker} aria-label="Manchester triage">
          <h3 className={styles.heading}>Manchester triage</h3>
          <p className={styles.sub}>Used by emergency departments</p>
          {MANCHESTER_TRIAGE.map((triage) => (
            <OptionButton
              key={triage.code}
              selected={scoreFor('manchester')?.value === triage.code}
              onSelect={() => setScore('manchester', { method: 'manchester', value: triage.code })}
              dataEl={`ADV-SCORE-MANCHESTER-${triage.code.toUpperCase()}`}
            >
              {triage.label}
            </OptionButton>
          ))}
          <p className={styles.note}>Only for referrers who have already triaged in an emergency department.</p>
        </section>
      ) : null}

      {methods.includes('news2') ? (
        <News2Picker
          initial={scoreFor('news2')?.value ?? null}
          onScore={(score) => setScore('news2', score === null ? null : { method: 'news2', value: score })}
        />
      ) : null}

      {methods.includes('cfs') ? (
        <CfsPicker
          chosen={scoreFor('cfs')?.value ?? null}
          onChoose={(next) => setScore('cfs', next === null ? null : { method: 'cfs', value: next })}
        />
      ) : null}

      <p className={styles.note}>
        Scores are recorded as the referrer gave them. The tool does not calculate or check them.
      </p>
    </fieldset>
  );
}

function News2Picker({ initial, onScore }: { initial: number | null; onScore: (score: number | null) => void }) {
  const [text, setText] = useState(initial === null ? '' : String(initial));
  const parsed = parseNews2(text);

  function change(next: string) {
    setText(next);
    const result = parseNews2(next);
    // An invalid entry is not recorded; it is shown as an error until it is corrected.
    onScore(result.valid ? result.value : null);
  }

  return (
    <div className={styles.picker}>
      <label className={styles.label} htmlFor="score-news2">
        NEWS2 score (0 to 20)
      </label>
      <input
        id="score-news2"
        className={styles.input}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        value={text}
        onChange={(event) => change(event.target.value)}
        aria-invalid={parsed.valid ? undefined : 'true'}
        aria-describedby={parsed.valid ? undefined : 'score-news2-error'}
        data-el="ADV-SCORE-NEWS2-INPUT"
      />
      {parsed.valid ? null : (
        <p id="score-news2-error" className={styles.error}>
          Enter a whole number from 0 to 20
        </p>
      )}
    </div>
  );
}

function CfsPicker({ chosen, onChoose }: { chosen: number | null; onChoose: (value: number | null) => void }) {
  const values = Array.from({ length: CFS_MAX - CFS_MIN + 1 }, (_, index) => CFS_MIN + index);
  return (
    <fieldset className={styles.picker}>
      <legend className={styles.label}>Clinical Frailty Scale (1 to 9)</legend>
      <div className={styles.chips}>
        {values.map((value) => (
          <Chip
            key={value}
            pressed={chosen === value}
            onPressedChange={(on) => onChoose(on ? value : null)}
            dataEl={`ADV-SCORE-CFS-${value}`}
          >
            {String(value)}
          </Chip>
        ))}
      </div>
      {chosen === null ? null : <p className={styles.sub}>{`${chosen} · ${CFS_LABELS[chosen]}`}</p>}
    </fieldset>
  );
}

function PathwaysPicker({ chosen, onChoose }: { chosen: string | null; onChoose: (code: string) => void }) {
  const [text, setText] = useState('');
  const [found, setFound] = useState<Found | null>(null);
  const [display, setDisplay] = useState<string | null>(null);
  const query = text.trim();
  const searching = query.length >= PATHWAYS_MIN_CHARACTERS;

  // One lookup per pause in typing (250 ms). A late answer for an old query is dropped.
  useEffect(() => {
    if (query.length < PATHWAYS_MIN_CHARACTERS) return;
    let live = true;
    const timer = setTimeout(() => {
      bffFetch<DxItem[]>(`/api/bff/terminology/pathways-dx?q=${encodeURIComponent(query)}`).then((reply) => {
        if (!live) return;
        setFound({ query, items: reply.ok && Array.isArray(reply.body) ? reply.body : [] });
      });
    }, PATHWAYS_DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query]);

  const results = searching && found !== null && found.query === query ? found.items : [];

  return (
    <section className={styles.picker} aria-label="NHS Pathways Dx">
      <h3 className={styles.heading}>NHS Pathways Dx</h3>
      <p className={styles.sub}>Used by 111 and ambulance telephone triage</p>
      <label className={styles.label} htmlFor="score-pathways-search">
        Search Dx code or description
      </label>
      <input
        id="score-pathways-search"
        className={styles.input}
        type="search"
        autoComplete="off"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      {results.length > 0 ? (
        <ul className={styles.results}>
          {results.map((item) => (
            <li key={item.code}>
              <button
                type="button"
                className={styles.result}
                data-el="ADV-SCORE-PATHWAYS-OPTION"
                onClick={() => {
                  setDisplay(item.display);
                  onChoose(item.code);
                }}
              >
                {`${item.code} · ${item.display}`}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {chosen === null ? null : (
        <p className={styles.sub}>{display === null ? `Chosen: ${chosen}` : `Chosen: ${chosen} · ${display}`}</p>
      )}
      <p className={styles.note}>Choose from the list. Codes cannot be typed freely.</p>
    </section>
  );
}
