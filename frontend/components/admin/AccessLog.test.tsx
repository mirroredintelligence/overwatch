import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AccessLog } from './AccessLog';

// "Who has accessed your organisation" (TEN-076, TEN-084): what the platform's own people did in this
// organisation, from the organisation's own chain, as a timeline. Each step says what was done, the role it was
// done in and the reference it was under; never a name or the opaque reference of the person.

const LOG = 'Access by the platform’s own people';

describe('AccessLog', () => {
  it('lists each step, newest first, as a timeline: what was done, who, when and the reference it was under', async () => {
    render(<AccessLog />);
    const list = await screen.findByRole('list', { name: LOG });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText('Opened access with a support code')).toBeInTheDocument();
    expect(within(items[0]!).getByText('Support · ref tkt-1, acc-1')).toBeInTheDocument();
    expect(within(items[0]!).getByText('29 Oct 2026, 10:00')).toBeInTheDocument();
    expect(within(items[1]!).getByText('Activated your organisation')).toBeInTheDocument();
    expect(within(items[1]!).getByText('Platform operator')).toBeInTheDocument();
  });

  it('marks the step that opened access as live and the others as past, in words as well as dots', async () => {
    render(<AccessLog />);
    const list = await screen.findByRole('list', { name: LOG });
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveAttribute('data-tone', 'normal');
    expect(items[1]).toHaveAttribute('data-tone', 'past');
  });

  it('shows no name or reference of a person', async () => {
    render(<AccessLog />);
    await screen.findByRole('list', { name: LOG });
    expect(document.body.textContent ?? '').not.toMatch(/ops-|stf-/);
  });

  it('offers the periods as buttons, 90 days pressed at first, and asks for the period the person chooses', async () => {
    const asked: string[] = [];
    server.use(
      http.get('/api/bff/tenant/access-log', ({ request }) => {
        asked.push(new URL(request.url).searchParams.get('days') ?? '');
        return HttpResponse.json({ entries: [] });
      }),
    );
    const user = userEvent.setup();
    render(<AccessLog />);
    await screen.findByText('Nobody from the platform has accessed your organisation in this time.');
    const group = screen.getByRole('group', { name: 'Show the last' });
    expect(within(group).getByRole('button', { name: 'Last 90 days' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'Last 30 days' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(within(group).getByRole('button', { name: 'Last 30 days' }));
    await waitFor(() => expect(asked).toEqual(['90', '30']));
    expect(within(group).getByRole('button', { name: 'Last 30 days' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(group).getByRole('button', { name: 'All' }));
    await waitFor(() => expect(asked).toEqual(['90', '30', '400']));
  });

  it('says it could not load, never an empty log, when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/access-log', () => HttpResponse.json({}, { status: 503 })));
    render(<AccessLog />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the access log.');
    expect(screen.queryByText('Nobody from the platform has accessed your organisation in this time.')).not.toBeInTheDocument();
  });

  it('says in a dashed box that nobody has accessed it in this time, when the log is empty', async () => {
    server.use(http.get('/api/bff/tenant/access-log', () => HttpResponse.json({ entries: [] })));
    render(<AccessLog />);
    expect(await screen.findByText('Nobody from the platform has accessed your organisation in this time.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: LOG })).not.toBeInTheDocument();
  });

  it('says how many it shows, and that the list stops at 200', async () => {
    render(<AccessLog />);
    await screen.findByRole('list', { name: LOG });
    expect(screen.getByText('2 steps shown. The list shows at most 200, newest first.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    render(<AccessLog />);
    await screen.findByRole('list', { name: LOG });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
