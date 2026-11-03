import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { QUEUE } from '@/test/fixtures/registration';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { server } from '@/test/msw/server';
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

  it('shows the state as a status tag, shape plus word, and the queue as a named list', async () => {
    const { container } = render(<RegistrationQueue />);
    const list = await screen.findByRole('list', { name: 'Registrations to review' });
    const tags = list.querySelectorAll('[data-variant]:not(a)');
    expect(tags.length).toBe(2);
    expect(tags[0]!.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(within(list).getByText('In review')).toBeInTheDocument();
    expect(container.querySelector('main')).toBeNull();
  });

  it('marks the open registration with aria-current and leaves the others unmarked', async () => {
    render(<RegistrationQueue selectedId="r1" />);
    const cards = await screen.findAllByRole('listitem');
    expect(cards[0]).toHaveAttribute('aria-current', 'true');
    expect(cards[1]).not.toHaveAttribute('aria-current');
  });

  it('copies the first problem into the card it belongs to, as a line with a triangle and the words', async () => {
    render(<RegistrationQueue selectedId="r1" problems={{ r1: 'Criteria owner email is not an organisation address' }} />);
    const cards = await screen.findAllByRole('listitem');
    const line = within(cards[0]!).getByText('Criteria owner email is not an organisation address');
    expect(line).toBeInTheDocument();
    expect(within(cards[0]!).getByText('Needs attention:')).toBeInTheDocument();
    expect(within(cards[1]!).queryByText('Needs attention:')).toBeNull();
  });

  it('shows a shimmer that says what is loading until the answer comes', async () => {
    render(<RegistrationQueue />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the registrations.');
    await screen.findByRole('list', { name: 'Registrations to review' });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('says what to do when nothing is waiting', async () => {
    server.use(
      http.get('/api/bff/registrations', () =>
        HttpResponse.json({ ...QUEUE, items: [] }, { headers: { 'Cache-Control': 'no-store' } }),
      ),
    );
    render(<RegistrationQueue />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Nothing to review' })).toBeInTheDocument();
    expect(screen.getByText(/New registrations appear here as soon as a service submits one/)).toBeInTheDocument();
  });

  it('says nothing was lost on an error, and asks again when Try again is pressed', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/registrations', () => HttpResponse.json({ error: 'x' }, { status: 500 })));
    render(<RegistrationQueue />);
    expect(await screen.findByRole('heading', { level: 2, name: /We could not load the registrations/ })).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been lost/)).toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('list', { name: 'Registrations to review' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });
});
