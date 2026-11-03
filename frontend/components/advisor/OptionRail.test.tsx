import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { OptionView } from '@/lib/advisor/options';
import { OptionRail } from './OptionRail';

// The other options, folded to the side of the one option that has the stage (the Call board, step 4).

function option(over: Partial<OptionView>): OptionView {
  return {
    serviceId: 'svc',
    name: 'Service',
    category: null,
    status: 'accepting',
    effectiveAvailable: null,
    overBy: null,
    unitLabel: null,
    travelText: null,
    dataAgeSeconds: null,
    staleWarning: false,
    criteriaVersion: null,
    fits: [],
    checks: [],
    phone: null,
    network: null,
    position: null,
    coverage: null,
    travel: null,
    ...over,
  };
}

const CURRENT = option({ serviceId: 'ucr-west', name: 'UCR West', effectiveAvailable: 4, unitLabel: 'referrals in the next 2 hrs' });
const HOME = option({ serviceId: 'hah', name: 'Hospital at home', status: 'over-capacity', overBy: 2, unitLabel: 'over established capacity' });
const WARD = option({ serviceId: 'ward-b', name: 'Community hospital · Ward B', effectiveAvailable: 5, unitLabel: 'beds free' });
const NETWORK = option({ serviceId: 'other-org', name: 'Elsewhere', network: { organisation: 'Other Trust', source: 'Reported by phone' } });

describe('OptionRail', () => {
  it('names itself Other options and lists every option but the current one, in the order given', () => {
    render(<OptionRail options={[CURRENT, HOME, WARD]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    const rail = screen.getByRole('complementary', { name: 'Other options' });
    expect(within(rail).getByRole('heading', { name: 'Other options' })).toBeInTheDocument();
    const items = within(rail).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Hospital at home');
    expect(items[1]).toHaveTextContent('Community hospital · Ward B');
    expect(within(rail).queryByText('UCR West')).toBeNull();
  });

  it('says the status as a word with the figure: Over capacity · +2, Accepting · 5 beds free', () => {
    render(<OptionRail options={[CURRENT, HOME, WARD]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    expect(screen.getByText('Over capacity · +2')).toBeInTheDocument();
    expect(screen.getByText('Accepting · 5 beds free')).toBeInTheDocument();
  });

  it('shows only the status word when the option has no figure', () => {
    render(<OptionRail options={[CURRENT, option({ serviceId: 'x', name: 'Quiet site', status: 'not-updated' })]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    expect(screen.getByText('Not updated')).toBeInTheDocument();
  });

  it('leaves a network service out: it never has a booking', () => {
    render(<OptionRail options={[CURRENT, NETWORK, WARD]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    expect(screen.queryByText('Elsewhere')).toBeNull();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('opens an option with the button named for it', async () => {
    const onOpen = vi.fn();
    render(<OptionRail options={[CURRENT, HOME, WARD]} currentServiceId="ucr-west" onOpen={onOpen} />);
    await userEvent.click(screen.getByRole('button', { name: /Hospital at home/ }));
    expect(onOpen).toHaveBeenCalledWith('hah');
  });

  it('says so when there is no other option, and has no buttons', () => {
    render(<OptionRail options={[CURRENT]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    expect(screen.getByText('No other options for this patient.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('is inert and hidden from assistive technology when folded, so Tab never lands in it', () => {
    const { container } = render(<OptionRail options={[CURRENT, HOME]} currentServiceId="ucr-west" folded onOpen={() => undefined} />);
    const rail = container.querySelector('aside');
    expect(rail).not.toBeNull();
    expect(rail).toHaveAttribute('inert');
    expect(rail).toHaveAttribute('aria-hidden', 'true');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('is not inert when open', () => {
    const { container } = render(<OptionRail options={[CURRENT, HOME]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    const rail = container.querySelector('aside');
    expect(rail).not.toHaveAttribute('inert');
    expect(rail).not.toHaveAttribute('aria-hidden');
  });

  it('has no axe violations', async () => {
    const { container } = render(<OptionRail options={[CURRENT, HOME, WARD]} currentServiceId="ucr-west" onOpen={() => undefined} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
