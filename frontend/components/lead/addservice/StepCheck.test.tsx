import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { blankService, type ServiceValues } from '@/lib/lead/serviceForm';
import { StepCheck } from './StepCheck';

// Step 4 of the add-a-service flow, "Check, then add it" (boards/lead/AddService.dc.html): three summary cards,
// each with Change, the warning that advisors see the criteria at once, Back and the one primary button.

const FILLED: ServiceValues = {
  ...blankService(),
  name: 'Hospital at home East',
  category: 'hospital-at-home-or-virtual-ward',
  measure: 'free-beds',
  unitLabel: 'virtual beds',
  establishedCapacity: '12',
  usualMin: '8',
  usualMax: '12',
  cadence: 'every-2-hrs',
  channel: 'text',
  mobile: '07700 900456',
  roleName: 'Duty manager',
  availableFrom: '08:00',
  availableTo: '20:00',
  ageMin: '18',
  ageMax: '',
  districts: 'DT1, DT2',
  accepts: ['frailty', 'fall-no-injury'],
  excludes: ['suspected-fracture', 'head-injury-anticoagulants'],
  reviewBy: '2031-12-12',
};

function setup(overrides: { values?: ServiceValues; busy?: boolean; problem?: string } = {}) {
  const calls = { onChange: vi.fn(), onBack: vi.fn(), onAdd: vi.fn() };
  render(<StepCheck values={FILLED} {...calls} {...overrides} />);
  return calls;
}

describe('StepCheck', () => {
  it('has the heading "Check, then add it" and a labelled group', () => {
    setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Check, then add it' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Check, then add it' })).toBeInTheDocument();
  });

  it('summarises the service in its first card', () => {
    setup();
    const card = screen.getByRole('group', { name: 'The service' });
    expect(card).toHaveTextContent('Hospital at home East');
    expect(card).toHaveTextContent('Hospital at home or virtual ward');
    expect(card).toHaveTextContent('Counts beds free');
    expect(card).toHaveTextContent('12 established, usually 8 to 12');
    expect(card).toHaveTextContent('08:00 to 20:00');
  });

  it('summarises who reports in its second card, with the last four digits of the phone only', () => {
    setup();
    const card = screen.getByRole('group', { name: 'Who reports' });
    expect(card).toHaveTextContent('Duty manager, by text');
    expect(card).toHaveTextContent('Phone ending 0456');
    expect(card).toHaveTextContent('Every 2 hrs');
    expect(card).not.toHaveTextContent('07700');
  });

  it('does not show an email address, and says it is by email', () => {
    setup({ values: { ...FILLED, channel: 'email', email: 'duty@example.org' } });
    const card = screen.getByRole('group', { name: 'Who reports' });
    expect(card).toHaveTextContent('Duty manager, by email');
    expect(card).not.toHaveTextContent('duty@example.org');
  });

  it('summarises who it takes in its third card', () => {
    setup();
    const card = screen.getByRole('group', { name: 'Who it takes' });
    expect(card).toHaveTextContent('Frailty, Fall, no injury');
    expect(card).toHaveTextContent('Age 18+');
    expect(card).toHaveTextContent('DT1, DT2');
    expect(card).toHaveTextContent('Not suspected fracture or head injury on anticoagulants');
    expect(card).toHaveTextContent('Review by 12 Dec 2031');
  });

  it('shows an age range when there is an oldest age', () => {
    setup({ values: { ...FILLED, ageMax: '65' } });
    expect(screen.getByRole('group', { name: 'Who it takes' })).toHaveTextContent('Age 18 to 65');
  });

  it('has a Change in each card that names its step', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(within(screen.getByRole('group', { name: 'The service' })).getByRole('button', { name: 'Change the service' }));
    await user.click(within(screen.getByRole('group', { name: 'Who reports' })).getByRole('button', { name: 'Change who reports' }));
    await user.click(within(screen.getByRole('group', { name: 'Who it takes' })).getByRole('button', { name: 'Change who it takes' }));
    expect(onChange.mock.calls).toEqual([[0], [1], [2]]);
  });

  it('warns that advisors will see the criteria as soon as the service is added, and when they are reviewed', () => {
    setup();
    expect(screen.getByText(/Advisors will see these criteria as soon as you add the service/)).toBeInTheDocument();
    expect(screen.getByText(/reviewed by 12 Dec 2031/)).toBeInTheDocument();
  });

  it('has Back and "Add the service"', async () => {
    const user = userEvent.setup();
    const { onBack, onAdd } = setup();
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it('disables the button while the service is being added', () => {
    setup({ busy: true });
    expect(screen.getByRole('button', { name: 'Add the service' })).toBeDisabled();
  });

  it('says in an alert when the service could not be added', () => {
    setup({ problem: 'The service could not be saved.' });
    expect(screen.getByRole('alert')).toHaveTextContent('The service could not be saved.');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <StepCheck values={FILLED} onChange={() => undefined} onBack={() => undefined} onAdd={() => undefined} problem="The service could not be saved." />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
