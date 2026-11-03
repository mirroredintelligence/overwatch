import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OverdueNotice } from './OverdueNotice';

// The owner's notice that the review date has passed. It names the date, says what advisors see, and offers
// two ways on: review now, or ask for the owner to be changed. Asking only shows the shift lead as text.

describe('OverdueNotice', () => {
  it('says when the criteria were last due to be reviewed, and what advisors see', async () => {
    const { container } = render(<OverdueNotice serviceName="UCR West" overdueSince="2026-09-12" />);
    expect(screen.getByRole('heading', { level: 2, name: 'Criteria not reviewed since 12 Sep' })).toBeInTheDocument();
    expect(screen.getByText('Advisors see a flag on UCR West: “criteria not reviewed”.')).toBeInTheDocument();
    expect(screen.getByText('Not your service any more? Ask the shift lead to change the owner.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('calls onReview from Review now, and says nothing about the owner yet', async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(<OverdueNotice serviceName="UCR West" overdueSince="2026-09-12" onReview={onReview} />);
    await user.click(screen.getByRole('button', { name: 'Review now' }));
    expect(onReview).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Shift lead:/)).not.toBeInTheDocument();
  });

  it('shows the shift lead role and phone as text when asked to change the owner, and sends nothing', async () => {
    const user = userEvent.setup();
    render(
      <OverdueNotice
        serviceName="UCR West"
        overdueSince="2026-09-12"
        shiftLead={{ role: 'Duty manager', phone: '01202 000 333' }}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Ask to change the owner' }));
    expect(screen.getByText('Shift lead: Duty manager, 01202 000 333. No message is sent.')).toBeInTheDocument();
  });

  it('asks the shift lead in words when no shift lead is on record', async () => {
    const user = userEvent.setup();
    render(<OverdueNotice serviceName="UCR West" overdueSince="2026-09-12" />);
    await user.click(screen.getByRole('button', { name: 'Ask to change the owner' }));
    expect(screen.getByText('Ask the shift lead to change the owner. No message is sent.')).toBeInTheDocument();
  });
});
