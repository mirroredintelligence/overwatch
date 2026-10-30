import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { RegistrationQueue } from './RegistrationQueue';

beforeEach(() => resetRegistrationRequests());

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('RegistrationQueue', () => {
  it('labels the tabs with the counts the back end gives, and marks the selected tab', async () => {
    const { container } = render(<RegistrationQueue />);
    expect(await screen.findByRole('tab', { name: 'Waiting (2)' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Sent back (0)' })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tab', { name: 'Live (1)' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Not approved (0)' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for the waiting tab when it is chosen, and keeps every tab keyboard-reachable', async () => {
    const user = userEvent.setup();
    render(<RegistrationQueue />);
    await screen.findByRole('tab', { name: 'Waiting (2)' });

    for (const tab of screen.getAllByRole('tab')) {
      expect(tab).not.toHaveAttribute('tabindex', '-1');
    }

    await user.click(screen.getByRole('tab', { name: 'Sent back (0)' }));
    expect(screen.getByRole('tab', { name: 'Sent back (0)' })).toHaveAttribute('aria-selected', 'true');
    const last = seenRegistrationRequests.at(-1);
    expect(last?.path).toBe('/api/bff/registrations');
    expect(last?.search).toBe('?tab=sent-back');
  });

  it('lists each registration with its state, when it was submitted and by whom, and a Review link', async () => {
    render(<RegistrationQueue />);
    const review = (await screen.findAllByRole('link', { name: 'Review' }))[0]!;
    expect(review).toHaveAttribute('href', '/lead/registrations/r1');
    expect(review).toHaveAttribute('data-el', 'LEAD-REG-REVIEW-BTN');

    const card = review.closest('li');
    expect(card).not.toBeNull();
    const scoped = within(card!);
    expect(scoped.getByText('UCR East')).toBeInTheDocument();
    expect(scoped.getByText('Submitted')).toBeInTheDocument();
    expect(scoped.getByText('Submitted 14:30 by Duty manager')).toBeInTheDocument();
  });
});
