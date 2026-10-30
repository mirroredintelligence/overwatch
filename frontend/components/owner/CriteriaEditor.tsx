'use client';

import { useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { NumberStepper } from '@/components/ui/NumberStepper';
import {
  ACCEPT_CHOICES,
  EXCLUDE_CHOICES,
  NEED_LABELS,
  ageError,
  conflictError,
  districtShape,
  excludeLabel,
} from '@/lib/criteria/model';
import type { CriteriaValues, NeedCode } from '@/lib/criteria/types';
import styles from '@/components/lead/lead.module.css';

// The owner's edit step (W30, ui-screens CriteriaOwner screen 4). A need cannot be both accepted and
// not accepted: the conflict is shown as it arises and Preview stays unavailable until it is gone.
// Changed fields are labelled "Changed" against the version the owner started from.

const KNOWN_DISTRICTS = ['DT1', 'DT2', 'DT3', 'DT4'] as const;

const same = (a: readonly unknown[], b: readonly unknown[]) => a.length === b.length && a.every((value) => b.includes(value));

export function CriteriaEditor({
  initial,
  onPreview,
  onCancel,
}: {
  initial: CriteriaValues;
  onPreview: (values: CriteriaValues) => void;
  onCancel?: () => void;
}) {
  const ids = useId();
  const [accepts, setAccepts] = useState<NeedCode[]>(initial.accepts);
  const [excludes, setExcludes] = useState<NeedCode[]>(initial.excludes);
  const [ageMin, setAgeMin] = useState<number | null>(initial.ageMin);
  const [ageMaxText, setAgeMaxText] = useState(initial.ageMax === null ? '' : String(initial.ageMax));
  const [districts, setDistricts] = useState<string[]>(initial.districts);
  const [newDistrict, setNewDistrict] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  const ageMax: number | null = ageMaxText.trim() === '' ? null : Number(ageMaxText.trim());
  const conflict = conflictError(accepts, excludes);
  const ageProblem = ageMin === null ? 'Enter the youngest age' : ageError(ageMin, ageMax);
  const blocked = conflict !== null || ageProblem !== null;

  const toggle = <T extends string>(list: T[], value: T, set: (next: T[]) => void) =>
    set(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);

  const districtChoices = [...new Set([...KNOWN_DISTRICTS, ...initial.districts, ...districts])].sort();

  const addDistrict = () => {
    const value = newDistrict.trim().toUpperCase();
    if (!districtShape(value)) {
      setErrors((current) => ({ ...current, district: 'Enter a postcode district, such as DT5' }));
      return;
    }
    if (!districts.includes(value)) setDistricts([...districts, value]);
    setNewDistrict('');
    setErrors((current) => ({ ...current, district: '' }));
  };

  const preview = () => {
    const found: Record<string, string> = {};
    if (conflict !== null) found.conflict = conflict;
    if (ageProblem !== null) found.age = ageProblem;
    if (districts.length === 0) found.districts = 'Choose at least one postcode district';
    setErrors(found);
    if (Object.keys(found).length > 0 || ageMin === null) return;
    onPreview({ accepts, excludes, ageMin, ageMax, districts });
  };

  const changed = (label: string, isChanged: boolean) =>
    isChanged ? <span className={styles.tag} data-field={label}>Changed</span> : null;

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Edit criteria</h1>

      {conflict !== null ? <p role="alert" className={styles.error}>{conflict}</p> : null}

      <fieldset className={styles.fieldset}>
        <legend>Needs you accept</legend>
        <p className={styles.hint}>Required</p>
        {changed('Needs you accept', !same(accepts, initial.accepts))}
        {ACCEPT_CHOICES.map((need) => (
          <Chip key={need} pressed={accepts.includes(need)} onPressedChange={() => toggle(accepts, need, setAccepts)} dataEl={`OWN-CRIT-ACCEPT-${need.toUpperCase()}`}>
            {NEED_LABELS[need]}
          </Chip>
        ))}
      </fieldset>

      <div className={styles.field}>
        <NumberStepper
          label="Youngest age"
          value={ageMin}
          min={0}
          max={120}
          onChange={setAgeMin}
          placeholder="18"
          dataEl="OWN-CRIT-AGE-MIN"
        />
        {changed('Youngest age', ageMin !== initial.ageMin)}
      </div>

      <div className={styles.field}>
        <label htmlFor={`${ids}-oldest`}>Oldest age</label>
        <input
          id={`${ids}-oldest`}
          className={styles.input}
          inputMode="numeric"
          placeholder="No limit"
          value={ageMaxText}
          onChange={(e) => setAgeMaxText(e.target.value.replace(/\D/g, ''))}
          aria-invalid={ageProblem !== null && ageProblem !== 'Enter the youngest age'}
        />
        {changed('Oldest age', ageMax !== initial.ageMax)}
        {errors.age !== undefined ? <p role="alert" className={styles.error}>{errors.age}</p> : null}
      </div>

      <fieldset className={styles.fieldset}>
        <legend>Needs you do not accept</legend>
        <p className={styles.hint}>Required</p>
        {changed('Needs you do not accept', !same(excludes, initial.excludes))}
        {EXCLUDE_CHOICES.slice(0, 4).map((need) => (
          <Chip key={need} pressed={excludes.includes(need)} onPressedChange={() => toggle(excludes, need, setExcludes)} dataEl={`OWN-CRIT-EXCLUDE-${need.toUpperCase()}`}>
            {excludeLabel(need)}
          </Chip>
        ))}
        <Chip pressed={excludes.length === 0} onPressedChange={() => setExcludes([])} dataEl="OWN-CRIT-EXCLUDE-NONE">
          No exclusions
        </Chip>
        {EXCLUDE_CHOICES.slice(4).map((need) => (
          <Chip key={need} pressed={excludes.includes(need)} onPressedChange={() => toggle(excludes, need, setExcludes)} dataEl={`OWN-CRIT-EXCLUDE-${need.toUpperCase()}`}>
            {excludeLabel(need)}
          </Chip>
        ))}
      </fieldset>

      <fieldset className={styles.fieldset}>
        <legend>Postcode districts</legend>
        <p className={styles.hint}>Required</p>
        {changed('Postcode districts', !same(districts, initial.districts))}
        {districtChoices.map((district) => (
          <Chip
            key={district}
            pressed={districts.includes(district)}
            onPressedChange={() => toggle(districts, district, setDistricts)}
            dataEl={`OWN-CRIT-DISTRICT-${district}`}
          >
            {district}
          </Chip>
        ))}
        <div className={styles.field}>
          <label htmlFor={`${ids}-district`}>Add a postcode district</label>
          <input id={`${ids}-district`} className={styles.input} value={newDistrict} onChange={(e) => setNewDistrict(e.target.value)} />
          <Button variant="secondary" onClick={addDistrict} dataEl="OWN-CRIT-DISTRICT-ADD-BTN">
            Add
          </Button>
          {errors.district ? <p role="alert" className={styles.error}>{errors.district}</p> : null}
        </div>
        {errors.districts !== undefined ? <p role="alert" className={styles.error}>{errors.districts}</p> : null}
      </fieldset>

      <div className={styles.actions}>
        <Button variant="primary" disabled={blocked} onClick={preview} dataEl="OWN-CRIT-PREVIEW-BTN">
          Preview
        </Button>
        <Button variant="neutral" onClick={() => onCancel?.()}>
          Cancel
        </Button>
      </div>
    </main>
  );
}
