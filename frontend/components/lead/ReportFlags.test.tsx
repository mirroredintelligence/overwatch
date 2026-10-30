import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { ReportFlags } from './ReportFlags';

// Reports to check (W42): the rules' flags on the open list. Accepting a figure or marking it checked
// moves the flag out of "To check"; a suspension is made from its own page.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('ReportFlags', () => {
  it('lists the flags with their summary, and a footnote on the rules', async () => {
    render(<ReportFlags />);
    expect(await screen.findByRole('tab', { name: 'To check (2)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'UCR East' })).toBeInTheDocument();
    expect(screen.getByText('The figure was out of its usual range twice.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Flagged by rules: out-of-range twice, many changes in a short time, or a figure that differs from what advisors recorded by phone.',
      ),
    ).toBeInTheDocument();
  });

  it('offers Phone to confirm, Accept the figure and Suspend service for an out-of-range flag', async () => {
    render(<ReportFlags />);
    const card = (await screen.findByRole('heading', { name: 'UCR East' })).closest('section') as HTMLElement;
    expect(within(card).getByRole('button', { name: 'Phone to confirm' })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Accept the figure' })).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Suspend service' })).toHaveAttribute(
      'href',
      '/lead/services/s-ucr-east/suspend',
    );
  });

  it('accepts the figure with the accept action, and moves the flag out of To check', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    const card = (await screen.findByRole('heading', { name: 'UCR East' })).closest('section') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Accept the figure' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/flags/flag-1',
      csrf: 'test-csrf-token',
      body: { action: 'accept' },
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Moved to Checked.');
    expect(screen.queryByRole('heading', { name: 'UCR East' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'To check (1)' })).toBeInTheDocument();
  });

  it('offers Phone to confirm and Mark as checked for a many-changes flag', async () => {
    render(<ReportFlags />);
    const card = (await screen.findByRole('heading', { name: 'Reablement' })).closest('section') as HTMLElement;
    expect(within(card).getByRole('button', { name: 'Phone to confirm' })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Mark as checked' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Accept the figure' })).not.toBeInTheDocument();
  });

  it('answers a 403 from the list with the words for a person who may not do this', async () => {
    server.use(http.get('/api/bff/lead/flags', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<ReportFlags />);
    expect(await screen.findByRole('alert')).toHaveTextContent('You cannot do this. Ask a shift lead.');
  });

  it('has no axe violations', async () => {
    const { container } = render(<ReportFlags />);
    await screen.findByRole('heading', { name: 'UCR East' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
