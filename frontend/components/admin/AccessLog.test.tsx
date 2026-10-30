import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AccessLog } from './AccessLog';

// "Who has accessed your organisation" (TEN-076, TEN-084): what the platform's own people did in this
// organisation, from the organisation's own chain. The role and the step in plain words and the ticket it
// was under; never a name or the opaque reference of the person.

describe('AccessLog', () => {
  it('lists each step, newest first, with the role, what was done and the reference it was under', async () => {
    render(<AccessLog />);
    const table = await screen.findByRole('table', { name: 'Access by the platform’s own people' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['When', 'Who', 'What happened', 'Reference']);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(within(rows[0]!).getByText('29 Oct 2026, 11:00')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Support')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Opened access with a support code')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('tkt-1, acc-1')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Platform operator')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Activated your organisation')).toBeInTheDocument();
  });

  it('shows no name or reference of a person', async () => {
    render(<AccessLog />);
    await screen.findByRole('table');
    expect(document.body.textContent ?? '').not.toMatch(/ops-|stf-/);
  });

  it('asks for 90 days at first, and for the days the person chooses', async () => {
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
    await user.selectOptions(screen.getByRole('combobox', { name: 'Show the last' }), '30');
    await waitFor(() => expect(asked).toEqual(['90', '30']));
  });

  it('says it could not load, never an empty log, when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/access-log', () => HttpResponse.json({}, { status: 503 })));
    render(<AccessLog />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the access log.');
    expect(screen.queryByText('Nobody from the platform has accessed your organisation in this time.')).not.toBeInTheDocument();
  });

  it('says how many it shows, and that the list stops at 200', async () => {
    render(<AccessLog />);
    await screen.findByRole('table');
    expect(screen.getByText('2 steps shown. The list shows at most 200, newest first.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    render(<AccessLog />);
    await screen.findByRole('table');
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
