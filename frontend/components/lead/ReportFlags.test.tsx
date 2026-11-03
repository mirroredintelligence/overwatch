import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { ReportFlags } from './ReportFlags';

// Reports to check (W42, LDR-09): the rules' flags as a master list and the open flag beside it. Accepting a
// figure or marking it checked moves the flag out of "To check"; a suspension is made from its own page.
// The "last reports" strip is not drawn: the flag resource carries no figures.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

async function openDetail(name: string): Promise<HTMLElement> {
  return (await screen.findByRole('region', { name })) as HTMLElement;
}

describe('ReportFlags', () => {
  it('has the page heading, the two tabs, and a list of the flags with their reasons in words', async () => {
    render(<ReportFlags />);
    expect(screen.getByRole('heading', { level: 1, name: 'Reports to check' })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: 'To check (2)' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Checked' })).toHaveAttribute('aria-selected', 'false');
    const list = screen.getByRole('list', { name: 'Flagged reports' });
    expect(within(list).getByRole('button', { name: /UCR East/ })).toHaveTextContent(
      'The figure was out of its usual range twice.',
    );
    expect(within(list).getByRole('button', { name: /Reablement/ })).toBeInTheDocument();
  });

  it('keeps the footnote visible, and says the rules never assess advisors', async () => {
    render(<ReportFlags />);
    await screen.findByRole('tab', { name: 'To check (2)' });
    expect(
      screen.getByText(/Flagged by rules: out-of-range twice, many changes in a short time, or a figure that differs from what advisors recorded by phone\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/never used to assess advisors/)).toBeInTheDocument();
  });

  it('opens the first flag beside the list, with the reason and the actions explained', async () => {
    render(<ReportFlags />);
    const detail = await openDetail('UCR East');
    expect(within(detail).getByRole('heading', { level: 2, name: 'UCR East' })).toBeInTheDocument();
    expect(within(detail).getByText('Report to check')).toBeInTheDocument();
    expect(within(detail).getByText('The figure was out of its usual range twice.')).toBeInTheDocument();
    expect(within(detail).getByText(/Their answer replaces the flagged figure/)).toBeInTheDocument();
    expect(within(detail).getByText(/You looked and the figure is right/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /UCR East/ })).toHaveAttribute('aria-current', 'true');
  });

  it('does not draw the last-reports strip, since the flag has no figures', async () => {
    render(<ReportFlags />);
    await openDetail('UCR East');
    expect(screen.queryByText('The last reports')).not.toBeInTheDocument();
  });

  it('offers Phone to confirm, Accept the figure and Suspend this service for an out-of-range flag', async () => {
    render(<ReportFlags />);
    const detail = await openDetail('UCR East');
    expect(within(detail).getByRole('button', { name: 'Phone to confirm' })).toBeInTheDocument();
    expect(within(detail).getByRole('button', { name: 'Accept the figure' })).toBeInTheDocument();
    expect(within(detail).getByRole('link', { name: 'Suspend this service' })).toHaveAttribute(
      'href',
      '/lead/services/s-ucr-east/suspend',
    );
  });

  it('opens another flag when it is chosen in the list, with Mark as checked for a many-changes flag', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    await openDetail('UCR East');
    await user.click(screen.getByRole('button', { name: /Reablement/ }));
    const detail = await openDetail('Reablement');
    expect(within(detail).getByRole('button', { name: 'Phone to confirm' })).toBeInTheDocument();
    expect(within(detail).getByRole('button', { name: 'Mark as checked' })).toBeInTheDocument();
    expect(within(detail).queryByRole('button', { name: 'Accept the figure' })).not.toBeInTheDocument();
    expect(within(detail).getByRole('link', { name: 'Suspend this service' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Reablement/ })).toHaveAttribute('aria-current', 'true');
  });

  it('accepts the figure with the accept action, moves the flag out of To check, and opens the next one', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    const detail = await openDetail('UCR East');
    await user.click(within(detail).getByRole('button', { name: 'Accept the figure' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/flags/flag-1',
      csrf: 'test-csrf-token',
      body: { action: 'accept' },
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Moved to Checked.');
    expect(screen.queryByRole('button', { name: /UCR East/ })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'To check (1)' })).toBeInTheDocument();
    expect(await openDetail('Reablement')).toBeInTheDocument();
  });

  it('marks a many-changes flag as checked with the checked action', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    await openDetail('UCR East');
    await user.click(screen.getByRole('button', { name: /Reablement/ }));
    const detail = await openDetail('Reablement');
    await user.click(within(detail).getByRole('button', { name: 'Mark as checked' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/flags/flag-2', body: { action: 'checked' } });
  });

  it('opens the phoned dialog for the open flag from Phone to confirm', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    const detail = await openDetail('UCR East');
    await user.click(within(detail).getByRole('button', { name: 'Phone to confirm' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('on a phone, a tap opens the flag in a step of its own, with a way back to the list', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    await openDetail('UCR East');
    const stage = screen.getByTestId('flags-stage');
    expect(stage).toHaveAttribute('data-step', 'list');
    expect(screen.queryByRole('button', { name: 'Back to the list' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Reablement/ }));
    expect(stage).toHaveAttribute('data-step', 'detail');
    await user.click(screen.getByRole('button', { name: 'Back to the list' }));
    expect(stage).toHaveAttribute('data-step', 'list');
  });

  it('moves between the tabs with the arrow keys, and the Checked tab has no actions', async () => {
    const user = userEvent.setup();
    render(<ReportFlags />);
    await openDetail('UCR East');
    screen.getByRole('tab', { name: 'To check (2)' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Checked' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Checked' })).toHaveFocus();
    const detail = await openDetail('UCR East');
    expect(within(detail).queryByRole('button', { name: 'Phone to confirm' })).not.toBeInTheDocument();
    expect(screen.getByRole('tabpanel')).toBeInTheDocument();
  });

  it('says "No reports to check." when the list is empty', async () => {
    server.use(http.get('/api/bff/lead/flags', () => HttpResponse.json({ counts: { toCheck: 0, checked: 0 }, items: [] })));
    render(<ReportFlags />);
    expect(await screen.findByText('No reports to check.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'To check (0)' })).toBeInTheDocument();
  });

  it('answers a 403 from the list with the words for a person who may not do this', async () => {
    server.use(http.get('/api/bff/lead/flags', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<ReportFlags />);
    expect(await screen.findByRole('alert')).toHaveTextContent('You cannot do this. Ask a shift lead.');
  });

  it('answers a failed read with an alert and a Try again button that reads again', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/lead/flags', () => HttpResponse.json({}, { status: 500 }), { once: true }));
    render(<ReportFlags />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load these reports.');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await openDetail('UCR East')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ReportFlags />);
    await openDetail('UCR East');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
