import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetCriteriaRequests, seenCriteriaRequests } from '@/test/msw/handlers/criteria';
import { CriteriaConfirm } from './CriteriaConfirm';

const CONFIRM = '/api/bff/criteria/s1/confirm';
beforeEach(() => resetCriteriaRequests());
const posts = () => seenCriteriaRequests.filter((r) => r.method === 'POST' && r.path === CONFIRM);

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CriteriaConfirm', () => {
  it('asks for a review period before it confirms, and posts the one chosen', async () => {
    const user = userEvent.setup();
    const { container } = render(<CriteriaConfirm serviceId="s1" version={3} />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Are these still right?' })).toBeInTheDocument();
    expect(screen.getByText('By confirming, you say the criteria are current and safe for advisors to rely on.')).toBeInTheDocument();
    expect(screen.getByText('We log your confirmation, the date and your role.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'I confirm' }));
    expect(await screen.findByText('Choose when to review again')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: '6 months' }));
    await user.click(screen.getByRole('button', { name: 'I confirm' }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ reviewInMonths: 6 });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
