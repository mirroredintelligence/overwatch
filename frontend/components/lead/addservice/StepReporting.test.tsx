import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { blankService, type FieldError, type ServiceValues } from '@/lib/lead/serviceForm';
import { StepReporting } from './StepReporting';

// Step 2 of the add-a-service flow, "Who reports, and how" (boards/lead/AddService.dc.html): text or email, the
// number or the address, the role that holds the phone, the cadence, and a note that nothing is sent now.

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
    <StepReporting
      values={values}
      set={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
      errors={errors}
      onNext={onNext}
      onBack={onBack}
    />
  );
}

describe('StepReporting', () => {
  it('has the heading "Who reports, and how" and a labelled group', () => {
    render(<Host />);
    expect(screen.getByRole('heading', { level: 1, name: 'Who reports, and how' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Who reports, and how' })).toBeInTheDocument();
  });

  it('asks for a mobile number by default, with the hints of the board', () => {
    render(<Host />);
    expect(screen.getByLabelText('Mobile number for text')).toHaveAccessibleDescription('A ward or team phone is best.');
    expect(screen.getByLabelText('Who holds this phone')).toHaveAccessibleDescription("A role, never a person's name.");
    expect(screen.queryByLabelText('Email')).toBeNull();
    expect(screen.getByRole('button', { name: 'Text' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('asks for an email address instead once Email is chosen', async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByRole('button', { name: 'Email' }));
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.queryByLabelText('Mobile number for text')).toBeNull();
  });

  it('has the three cadences as chips', () => {
    render(<Host />);
    const group = screen.getByRole('group', { name: 'Usual cadence' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['Every 2 hrs', 'Twice a day', 'Once a day']);
  });

  it('says nothing is sent now', () => {
    render(<Host />);
    expect(screen.getByText(/Nothing is sent now/)).toBeInTheDocument();
  });

  it('has Back and "Next: who it takes"', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    const onBack = vi.fn();
    render(<Host onNext={onNext} onBack={onBack} />);
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: 'Next: who it takes' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onNext).toHaveBeenCalledWith(false);
  });

  it('goes on with Enter in a field, said to be by the keyboard', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    render(<Host onNext={onNext} />);
    await user.type(screen.getByLabelText('Who holds this phone'), 'Duty manager{Enter}');
    expect(onNext).toHaveBeenCalledWith(true);
  });

  it('shows the summary of problems at the top, and the mobile message by its field', () => {
    const message = 'Enter a UK mobile number, like 07700 900456';
    render(<Host errors={[{ field: 'lead-add-mobile', message }]} />);
    expect(within(screen.getByRole('alert')).getByRole('link', { name: message })).toBeInTheDocument();
    expect(screen.getByLabelText('Mobile number for text')).toHaveAccessibleDescription(
      `A ward or team phone is best. ${message}`,
    );
  });

  it('has no axe violations, with problems shown', async () => {
    const { container } = render(<Host errors={[{ field: 'lead-add-role', message: 'Enter who holds this phone' }]} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
