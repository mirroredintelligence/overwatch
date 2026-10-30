import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { ScopeCheck } from './ScopeCheck';

const SCOPE = '/api/bff/registrations/r1/scope';
beforeEach(() => resetRegistrationRequests());
const posts = (path: string) => seenRegistrationRequests.filter((r) => r.method === 'POST' && r.path === path);
const QUESTIONS = [
  'Is the service part of the Dorset urgent care pathway?',
  'Does it take referrals from the coordination team?',
  'Can it report by app, text or email?',
  'Is its category on the pilot list?',
];

// One query for the four answer sets, in question order: a name query per click is too slow here.
async function answerAll(user: ReturnType<typeof userEvent.setup>, answer: string) {
  const buttons = screen.getAllByRole('button', { name: answer });
  expect(buttons).toHaveLength(QUESTIONS.length);
  for (const button of buttons) {
    await user.click(button);
  }
}


// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('ScopeCheck', () => {
  it('blocks "Out of scope" without a reason, and saves "In scope: pilot" without one', async () => {
    const user = userEvent.setup();
    const { container } = render(<ScopeCheck id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Is it in scope?' })).toBeInTheDocument();
    expect(screen.getByText('Check 2 of 4')).toBeInTheDocument();

    await answerAll(user, 'Yes');
    await user.click(screen.getByRole('button', { name: 'Out of scope' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Enter a reason')).toBeInTheDocument();
    expect(posts(SCOPE)).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'In scope: pilot' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(posts(SCOPE)).toHaveLength(1));
    expect(posts(SCOPE)[0]?.body).toEqual({
      answers: { pathway: 'yes', spoaReferrals: 'yes', canReport: 'yes', categoryOnList: 'yes' },
      decision: 'in-pilot',
    });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for every question to be answered before it saves', async () => {
    const user = userEvent.setup();
    render(<ScopeCheck id="r1" />);
    await screen.findByRole('heading', { level: 1, name: 'Is it in scope?' });
    await user.click(screen.getAllByRole('button', { name: 'Yes' })[0]!);
    await user.click(screen.getByRole('button', { name: 'In scope: pilot' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Answer every question')).toBeInTheDocument();
    expect(posts(SCOPE)).toHaveLength(0);
  });
});
