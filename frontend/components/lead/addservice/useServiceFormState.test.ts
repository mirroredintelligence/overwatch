import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { STEP_COUNT, stepOfField, useServiceFormState } from './useServiceFormState';

// One form state for the add-a-service steps, in memory only. The checks are lib/lead/serviceForm.ts's, run for
// the fields of one step at a time.

const fieldsOf = (errors: { field: string }[]) => errors.map((e) => e.field);

describe('useServiceFormState', () => {
  it('starts blank, with no problems', () => {
    const { result } = renderHook(() => useServiceFormState());
    expect(result.current.values.name).toBe('');
    expect(result.current.values.channel).toBe('text');
    expect(result.current.errors).toEqual([]);
  });

  it('changes one value and keeps the others', () => {
    const { result } = renderHook(() => useServiceFormState());
    act(() => result.current.set('name', 'Reablement'));
    act(() => result.current.set('allDay', true));
    expect(result.current.values.name).toBe('Reablement');
    expect(result.current.values.allDay).toBe(true);
  });

  it('adds a need and takes it away again', () => {
    const { result } = renderHook(() => useServiceFormState());
    act(() => result.current.toggle('accepts', 'frailty'));
    act(() => result.current.toggle('accepts', 'dementia'));
    expect(result.current.values.accepts).toEqual(['frailty', 'dementia']);
    act(() => result.current.toggle('accepts', 'frailty'));
    expect(result.current.values.accepts).toEqual(['dementia']);
  });

  it('has three steps for now, and says which step a field is on', () => {
    expect(STEP_COUNT).toBe(3);
    expect(stepOfField('lead-add-name')).toBe(0);
    expect(stepOfField('lead-add-to')).toBe(0);
    expect(stepOfField('lead-add-mobile')).toBe(1);
    expect(stepOfField('lead-add-role')).toBe(1);
    expect(stepOfField('lead-add-districts')).toBe(2);
    expect(stepOfField('lead-add-review')).toBe(2);
  });

  it('checks only the fields of step 1 and shows them', () => {
    const { result } = renderHook(() => useServiceFormState());
    let found: { field: string }[] = [];
    act(() => {
      found = result.current.check(0);
    });
    expect(fieldsOf(found)).toEqual([
      'lead-add-name',
      'lead-add-category',
      'lead-add-measure',
      'lead-add-established',
      'lead-add-from',
      'lead-add-to',
    ]);
    expect(fieldsOf(result.current.errors)).toEqual(fieldsOf(found));
  });

  it('checks only the fields of step 2, and asks for the email when the channel is email', () => {
    const { result } = renderHook(() => useServiceFormState());
    act(() => {
      result.current.check(1);
    });
    expect(fieldsOf(result.current.errors)).toEqual(['lead-add-cadence', 'lead-add-mobile', 'lead-add-role']);
    act(() => result.current.set('channel', 'email'));
    act(() => {
      result.current.check(1);
    });
    expect(fieldsOf(result.current.errors)).toEqual(['lead-add-cadence', 'lead-add-email', 'lead-add-role']);
  });

  it('checks only the fields of step 3', () => {
    const { result } = renderHook(() => useServiceFormState());
    act(() => {
      result.current.check(2);
    });
    expect(fieldsOf(result.current.errors)).toEqual([
      'lead-add-age-min',
      'lead-add-districts',
      'lead-add-accepts',
      'lead-add-review',
    ]);
  });

  it('shows no problem once the step is right', () => {
    const { result } = renderHook(() => useServiceFormState());
    act(() => {
      result.current.check(0);
    });
    expect(result.current.errors.length).toBeGreaterThan(0);
    act(() => result.current.set('name', 'Reablement'));
    act(() => result.current.set('category', 'reablement'));
    act(() => result.current.set('measure', 'free-beds'));
    act(() => result.current.set('establishedCapacity', '4'));
    act(() => result.current.set('availableFrom', '08:00'));
    act(() => result.current.set('availableTo', '20:00'));
    let found: { field: string }[] = [{ field: 'x' }];
    act(() => {
      found = result.current.check(0);
    });
    expect(found).toEqual([]);
    expect(result.current.errors).toEqual([]);
  });

  it('on a final check, shows the problems of the earliest step that has any, and says which step', () => {
    const { result } = renderHook(() => useServiceFormState());
    let step: number | null = null;
    act(() => {
      step = result.current.checkAll();
    });
    expect(step).toBe(0);
    expect(fieldsOf(result.current.errors)).toContain('lead-add-name');
    expect(fieldsOf(result.current.errors)).not.toContain('lead-add-mobile');
  });

  it('clears the problems shown', () => {
    const { result } = renderHook(() => useServiceFormState());
    act(() => {
      result.current.check(0);
    });
    act(() => result.current.clearErrors());
    expect(result.current.errors).toEqual([]);
  });
});
