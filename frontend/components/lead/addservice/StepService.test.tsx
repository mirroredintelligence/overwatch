import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { blankService, type FieldError, type ServiceValues } from '@/lib/lead/serviceForm';
import { StepService } from './StepService';

// Step 1 of the add-a-service flow, "The service" (boards/lead/AddService.dc.html): the name, the category, what is
// counted, the unit label, the three numbers and the hours; one card, one primary button.

function Host({
  errors = [],
  onNext = () => undefined,
  initial,
}: {
  errors?: FieldError[];
  onNext?: (viaKeyboard: boolean) => void;
  initial?: Partial<ServiceValues>;
}) {
  const [values, setValues] = useState<ServiceValues>({ ...blankService(), ...initial });
  return (
    <StepService
      values={values}
      set={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
      errors={errors}
      onNext={onNext}
    />
  );
}

describe('StepService', () => {
  it('has the heading "The service" and a labelled group', () => {
    render(<Host />);
    expect(screen.getByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'The service' })).toBeInTheDocument();
  });

  it('has each field of the board, by its label', () => {
    render(<Host />);
    for (const label of ['Service name', 'Max capacity', 'From', 'To']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.queryByLabelText('Unit label')).toBeNull();
    expect(screen.queryByLabelText('Usual low')).toBeNull();
    expect(screen.getByLabelText('Takes referrals all day')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Days it takes referrals' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Category' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'What is counted' })).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'Category' })).getAllByRole('button')).toHaveLength(6);
    expect(screen.getByRole('button', { name: 'Hospital at home or virtual ward' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Beds free' })).toBeInTheDocument();
  });

  it('says you can change any of this later, and has no Back button', () => {
    render(<Host />);
    expect(screen.getByText(/You can change any of this later/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
  });

  it('keeps what is typed and which chip is pressed', async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.type(screen.getByLabelText('Service name'), 'Hospital at home East');
    await user.click(screen.getByRole('button', { name: 'Beds free' }));
    expect(screen.getByLabelText('Service name')).toHaveValue('Hospital at home East');
    expect(screen.getByRole('button', { name: 'Beds free' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Slots left today' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('goes on with "Next: who reports", said to be by the mouse', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    render(<Host onNext={onNext} />);
    await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
    expect(onNext).toHaveBeenCalledWith(false);
  });

  it('goes on with Enter in a field, said to be by the keyboard', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    render(<Host onNext={onNext} />);
    await user.type(screen.getByLabelText('Service name'), 'x{Enter}');
    expect(onNext).toHaveBeenCalledWith(true);
  });

  it('shows the summary of problems at the top, and each problem by its field', () => {
    const errors = [
      { field: 'lead-add-name', message: 'Enter the service name' },
      { field: 'lead-add-category', message: 'Choose a category' },
    ];
    render(<Host errors={errors} />);
    const summary = screen.getByRole('alert');
    expect(summary).toHaveTextContent('There are 2 problems');
    expect(within(summary).getByRole('link', { name: 'Choose a category' })).toBeInTheDocument();
    const name = screen.getByLabelText('Service name');
    expect(name).toHaveAccessibleDescription('Enter the service name');
  });

  it('moves focus to the first chip of a group from its problem link', async () => {
    const user = userEvent.setup();
    render(<Host errors={[{ field: 'lead-add-category', message: 'Choose a category' }]} />);
    await user.click(screen.getByRole('link', { name: 'Choose a category' }));
    expect(screen.getByRole('button', { name: 'Urgent community response' })).toHaveFocus();
  });

  it('has no axe violations, with problems shown', async () => {
    const { container } = render(<Host errors={[{ field: 'lead-add-name', message: 'Enter the service name' }]} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
