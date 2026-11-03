import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { blankService, type FieldError, type ServiceValues } from '@/lib/lead/serviceForm';
import { StepCriteria } from './StepCriteria';

// Step 3 of the add-a-service flow, "Who it takes" (boards/lead/AddService.dc.html): the needs accepted and not
// accepted, the ages, the districts and the review-by date. The owner of the criteria is not asked: the back end
// has no such field yet.

function Host({
  errors = [],
  onNext = () => undefined,
  onBack = () => undefined,
}: {
  errors?: FieldError[];
  onNext?: (viaKeyboard: boolean) => void;
  onBack?: () => void;
}) {
  const [values, setValues] = useState<ServiceValues>(blankService());
  return (
    <StepCriteria
      values={values}
      set={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
      toggle={(key, value) =>
        setValues((previous) => ({
          ...previous,
          [key]: previous[key].includes(value) ? previous[key].filter((item) => item !== value) : [...previous[key], value],
        }))
      }
      errors={errors}
      onNext={onNext}
      onBack={onBack}
    />
  );
}

describe('StepCriteria', () => {
  it('has the heading "Who it takes" and a labelled group', () => {
    render(<Host />);
    expect(screen.getByRole('heading', { level: 1, name: 'Who it takes' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Who it takes' })).toBeInTheDocument();
  });

  it('has the needs accepted and not accepted as chip groups', () => {
    render(<Host />);
    const accepts = screen.getByRole('group', { name: 'Needs you accept' });
    expect(within(accepts).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Fall, no injury',
      'Frailty',
      'Wound care',
      'IV therapy',
      'Palliative',
      'Dementia',
    ]);
    const excludes = screen.getByRole('group', { name: 'Needs you do not accept' });
    expect(within(excludes).getAllByRole('button')).toHaveLength(4);
  });

  it('presses a chip on and off', async () => {
    const user = userEvent.setup();
    render(<Host />);
    const chip = screen.getByRole('button', { name: 'Frailty' });
    await user.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    await user.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'false');
  });

  it('has the age, district and review fields, and does not ask who owns the criteria', () => {
    render(<Host />);
    expect(screen.getByLabelText('Youngest age')).toBeInTheDocument();
    expect(screen.getByLabelText('Oldest age')).toHaveAccessibleDescription('Leave blank for no limit');
    expect(screen.getByLabelText('Postcode districts')).toBeInTheDocument();
    expect(screen.getByLabelText('Review criteria by')).toBeInTheDocument();
    expect(screen.queryByText('Who owns these criteria')).toBeNull();
  });

  it('says the pilot is for text or email only', () => {
    render(<Host />);
    expect(screen.getByText('Services with neither text nor email are outside the MVP.')).toBeInTheDocument();
  });

  it('has Back and "Next: check", and no Save', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    const onBack = vi.fn();
    render(<Host onNext={onNext} onBack={onBack} />);
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: 'Next: check' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onNext).toHaveBeenCalledWith(false);
  });

  it('goes on with Enter in a field, said to be by the keyboard', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    render(<Host onNext={onNext} />);
    await user.type(screen.getByLabelText('Youngest age'), '18{Enter}');
    expect(onNext).toHaveBeenCalledWith(true);
  });

  it('shows the summary of problems at the top and the message by its field', () => {
    const message = 'Enter a postcode district, like DT4';
    render(<Host errors={[{ field: 'lead-add-districts', message }]} />);
    expect(within(screen.getByRole('alert')).getByRole('link', { name: message })).toBeInTheDocument();
    expect(screen.getByLabelText('Postcode districts')).toHaveAccessibleDescription(`Like DT4. Separate with commas. ${message}`);
  });

  it('has no axe violations, with problems shown', async () => {
    const { container } = render(<Host errors={[{ field: 'lead-add-accepts', message: 'Choose at least one need' }]} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
