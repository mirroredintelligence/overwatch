import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetCriteriaRequests, seenCriteriaRequests } from '@/test/msw/handlers/criteria';
import type { CriteriaValues } from '@/lib/criteria/types';
import { CriteriaSend } from './CriteriaSend';

const SUBMIT = '/api/bff/criteria/s1/submit';
beforeEach(() => resetCriteriaRequests());
const posts = () => seenCriteriaRequests.filter((r) => r.method === 'POST' && r.path === SUBMIT);
const VALUES: CriteriaValues = { accepts: ['fall-no-injury'], excludes: [], ageMin: 16, ageMax: null, districts: ['DT1'] };

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CriteriaSend', () => {
  it('asks for a reason, sends it with the review period, and shows the status with "Waiting for approval"', async () => {
    const user = userEvent.setup();
    render(<CriteriaSend serviceId="s1" currentVersion={3} changes={['Youngest age 18 to 16']} values={VALUES} />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Send for second approval' })).toBeInTheDocument();
    expect(screen.getByText('A clinical lead approves it too. Until then, advisors still see version 3.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Send for approval' }));
    expect(await screen.findByText('Enter why you are changing this')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Why are you changing this?'), 'Younger patients can be seen');
    await user.click(within(screen.getByRole('group', { name: 'Review again in' })).getByRole('button', { name: '6 months' }));
    await user.click(screen.getByRole('button', { name: 'Send for approval' }));
    expect(await screen.findByText('Waiting for approval')).toBeInTheDocument();
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toMatchObject({ reason: 'Younger patients can be seen', reviewInMonths: 6, ageMin: 16 });
    expect(screen.getByText('Advisors see version 4')).toBeInTheDocument();
    expect(await runAxe(screen.getByRole('status'))).toHaveNoViolations();
  });
});
