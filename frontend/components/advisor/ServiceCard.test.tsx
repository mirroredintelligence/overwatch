import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { categoryLabel, durationText } from '@/lib/board/format';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { OPTIONS_VIEW } from '@/test/fixtures/options';
import type { OptionView } from '@/lib/advisor/options';
import { resetBookingRequests, seenBookingPosts } from '@/test/msw/handlers/bookings';
import { ServiceCard } from './ServiceCard';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  resetBookingRequests();
  document.cookie = 'diucs_csrf=csrf-value-for-the-card; path=/';
});

const [UCR_WEST, WARD_B, HAH] = OPTIONS_VIEW.options as unknown as OptionView[];

function renderCard(option: OptionView, handlers = {}) {
  const props = { onCriteria: vi.fn(), onPhoned: vi.fn(), ...handlers };
  render(<ServiceCard caseId="case-1" option={option} {...props} />);
  return props;
}

describe('ServiceCard (W13)', () => {
  it('shows the name, category, status, number, unit, response, data age, why it fits and what to check', () => {
    renderCard(UCR_WEST);
    const card = screen.getByRole('article', { name: 'UCR West' });

    expect(within(card).getByText(categoryLabel('urgent-community-response'))).toBeInTheDocument();
    expect(within(card).getByText('Accepting')).toBeInTheDocument();
    expect(byEl('ADV-OPT-NUMBER', card)).toHaveTextContent('4');
    expect(within(card).getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(within(card).getByText(`Response or travel: about 35 to 50 min`)).toBeInTheDocument();
    expect(within(card).getByText(`Data age: ${durationText(9)} ago`)).toBeInTheDocument();
    expect(within(card).getByText('Why it fits')).toBeInTheDocument();
    expect(within(card).getByText('Covers this postcode')).toBeInTheDocument();
    expect(within(card).getByText('Check before offering')).toBeInTheDocument();
    expect(within(card).getByText('Visits after 18:00 need phone confirmation')).toBeInTheDocument();
  });

  it('adds the stale warning to the checks when the data is over 2 hrs old', () => {
    renderCard(WARD_B);
    const card = screen.getByRole('article', { name: 'Community hospital · Ward B' });

    expect(within(card).getByText('Data is over 2 hrs old. Consider phoning.')).toBeInTheDocument();
  });

  it('over capacity shows "+2" and the word "Over capacity"', () => {
    renderCard(HAH);
    const card = screen.getByRole('article', { name: 'Hospital at home' });

    expect(byEl('ADV-OPT-NUMBER', card)).toHaveTextContent('+2');
    expect(within(card).getByText('Over capacity')).toBeInTheDocument();
  });

  it('a figure with no unit reads "Phone to confirm", and no response line reads "Not recorded"', () => {
    renderCard({ ...UCR_WEST, unitLabel: null, travelText: null });
    const card = screen.getByRole('article', { name: 'UCR West' });

    expect(within(card).getByText('Phone to confirm')).toBeInTheDocument();
    expect(within(card).getByText('Response or travel: Not recorded')).toBeInTheDocument();
  });

  it('the booking control is the booking panel of this case and service, and the other buttons call their props with the service id', async () => {
    const user = userEvent.setup();
    const props = renderCard(UCR_WEST);

    await user.click(byEl('ADV-OPT-REQUEST-BTN'));
    expect(await screen.findByText('Requested')).toBeInTheDocument();
    expect(seenBookingPosts[0]?.body).toEqual({ caseRef: 'case-1', serviceId: 'svc-ucr-west' });
    await user.click(byEl('ADV-OPT-CRITERIA-BTN'));
    await user.click(byEl('ADV-OPT-PHONED-BTN'));

    expect(props.onCriteria).toHaveBeenCalledWith('svc-ucr-west');
    expect(props.onPhoned).toHaveBeenCalledWith('svc-ucr-west');
  });

  it('a network service shows its organisation and source, and has no booking, phoned or declined action', () => {
    renderCard({
      ...UCR_WEST,
      network: { organisation: 'Neighbouring', source: 'Entered by the organisation' },
    });
    const card = screen.getByRole('article', { name: 'UCR West' });

    expect(within(card).getByText('Neighbouring')).toBeInTheDocument();
    expect(within(card).getByText('Entered by the organisation')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Request booking' })).toBeNull();
    expect(within(card).queryByRole('button', { name: 'I phoned' })).toBeNull();
    expect(within(card).queryByRole('button', { name: 'They declined' })).toBeNull();
    // Its criteria are another organisation's: the own-service read would not find them (KI-794).
    expect(within(card).queryByRole('button', { name: 'Criteria' })).toBeNull();
  });

  it('shows the service phone as a link to phone it, for a service of the viewer and for a network service (Q5, KI-626)', () => {
    renderCard({ ...UCR_WEST, phone: '01305 900100' });
    expect(within(screen.getByRole('article', { name: 'UCR West' })).getByRole('link', { name: 'Phone 01305 900100' })).toHaveAttribute(
      'href',
      'tel:01305 900100',
    );
  });

  it('a network service has its phone as the one thing to do with it', () => {
    renderCard({
      ...UCR_WEST,
      phone: '01305 900300',
      network: { organisation: 'Neighbouring', source: 'Entered by the organisation' },
    });
    const card = screen.getByRole('article', { name: 'UCR West' });

    expect(within(card).getByRole('link', { name: 'Phone 01305 900300' })).toHaveAttribute('href', 'tel:01305 900300');
  });

  it('says no number is held, and invents none, when the service has none', () => {
    renderCard({ ...UCR_WEST, phone: null });
    const card = screen.getByRole('article', { name: 'UCR West' });

    expect(within(card).queryByRole('link', { name: /^Phone/ })).toBeNull();
    expect(within(card).getByText('No phone number is held for this service. Find it in your service directory.')).toBeInTheDocument();
  });

  it('has no rank, no "best" and no score', () => {
    renderCard(UCR_WEST);
    expect(screen.queryByText(/best|rank|score/i)).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ServiceCard caseId="case-1" option={WARD_B} onCriteria={() => {}} onPhoned={() => {}} />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
