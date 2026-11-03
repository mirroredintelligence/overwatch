import { render, screen, waitFor, within } from '@testing-library/react';
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
  it('is a card with a level 2 heading, not a page of its own: no main landmark and no level 1', async () => {
    render(<ScopeCheck id="r1" />);
    const heading = await screen.findByRole('heading', { level: 2, name: 'Is it in scope?' });
    expect(screen.queryByRole('main')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Is it in scope?' })).toContainElement(heading);
  });

  it('asks the four questions as named groups of three answers, then the decision as a group of three', async () => {
    render(<ScopeCheck id="r1" />);
    await screen.findByRole('heading', { level: 2, name: 'Is it in scope?' });
    for (const question of QUESTIONS) {
      const group = screen.getByRole('group', { name: question });
      expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['Yes', 'No', 'Not sure']);
    }
    const decision = screen.getByRole('group', { name: 'Your decision' });
    expect(within(decision).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByText('A reason is needed only if the decision is not the pilot.')).toBeInTheDocument();
  });

  it('marks the chosen answer with aria-pressed and a shape, not colour alone', async () => {
    const user = userEvent.setup();
    render(<ScopeCheck id="r1" />);
    await screen.findByRole('heading', { level: 2, name: 'Is it in scope?' });
    const first = within(screen.getByRole('group', { name: QUESTIONS[0]! })).getByRole('button', { name: 'Not sure' });
    expect(first).toHaveAttribute('aria-pressed', 'false');
    await user.click(first);
    expect(first).toHaveAttribute('aria-pressed', 'true');
    expect(first.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('says what is loading while the overview is read', () => {
    render(<ScopeCheck id="r1" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the scope check.');
    expect(screen.getByRole('heading', { level: 2, name: 'Is it in scope?' })).toBeInTheDocument();
  });

  it('blocks "Out of scope" without a reason, and saves "In scope: pilot" without one', async () => {
    const user = userEvent.setup();
    const { container } = render(<ScopeCheck id="r1" />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Is it in scope?' })).toBeInTheDocument();
    expect(screen.getByText('Check 2 of 4 · UCR East')).toBeInTheDocument();

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
    await screen.findByRole('heading', { level: 2, name: 'Is it in scope?' });
    await user.click(screen.getAllByRole('button', { name: 'Yes' })[0]!);
    await user.click(screen.getByRole('button', { name: 'In scope: pilot' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Answer every question')).toBeInTheDocument();
    expect(posts(SCOPE)).toHaveLength(0);
  });
});
