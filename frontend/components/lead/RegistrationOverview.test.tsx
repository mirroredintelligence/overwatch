import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW } from '@/test/fixtures/registration';
import { server } from '@/test/msw/server';
import { RegistrationOverview } from './RegistrationOverview';

function overviewWith(patch: Partial<typeof OVERVIEW>) {
  server.use(
    http.get('/api/bff/registrations/:id', () =>
      HttpResponse.json({ ...OVERVIEW, ...patch }, { headers: { 'Cache-Control': 'no-store' } }),
    ),
  );
}

describe('RegistrationOverview', () => {
  it('shows a failing automatic check with its warning and the action to take', async () => {
    const { container } = render(<RegistrationOverview id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR East' })).toBeInTheDocument();
    expect(screen.getByText('Registered by Sample Person, Duty manager')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Checks the system did' })).toBeInTheDocument();
    expect(screen.getByText('Criteria owner email is not an organisation address')).toBeInTheDocument();
    expect(screen.getByText('Ask for an organisation address')).toBeInTheDocument();
    expect(screen.getByText('Needs attention:')).toBeInTheDocument();
    expect(screen.getByText('ODS code found, active, NHS trust')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('reads check 4 as "Opens when 1 to 3 are done" and links the first check to the call-back page', async () => {
    render(<RegistrationOverview id="r1" />);
    expect(await screen.findByText('Opens when 1 to 3 are done')).toBeInTheDocument();
    const start = screen.getByRole('link', { name: 'Start with the call-back' });
    expect(start).toHaveAttribute('href', '/lead/registrations/r1?step=callback');
    expect(start).toHaveAttribute('data-el', 'LEAD-REG-START-CALLBACK-BTN');
  });

  it('lists "Checks you do" as a stepper: each check is a link to its own step, with its state in words', async () => {
    render(<RegistrationOverview id="r1" />);
    await screen.findByRole('heading', { level: 2, name: 'Checks you do' });
    const steps = screen.getByRole('list', { name: 'Checks you do' });
    const rows = within(steps).getAllByRole('listitem');
    expect(rows).toHaveLength(4);

    const callBack = within(rows[0]!).getByRole('link', { name: /1 Call the service back/ });
    expect(callBack).toHaveAttribute('href', '/lead/registrations/r1?step=callback');
    expect(within(rows[0]!).getByText('Not done')).toBeInTheDocument();

    expect(within(rows[1]!).getByRole('link', { name: /2 Is it in scope\?/ })).toHaveAttribute('href', '/lead/registrations/r1?step=scope');

    // The clinical lead's approval is somebody else's step: it is not a link.
    expect(within(rows[2]!).queryByRole('link')).toBeNull();
    expect(within(rows[2]!).getByText('3 Criteria second approval')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Waiting for the clinical lead')).toBeInTheDocument();

    expect(within(rows[3]!).getByRole('link', { name: /4 Decide/ })).toHaveAttribute('href', '/lead/registrations/r1?step=decide');
  });

  it('marks the finished checks done, and reads check 4 as ready when 1 to 3 are done', async () => {
    overviewWith({ manualChecks: { callback: 'done', scope: 'done', criteria: 'done' } });
    render(<RegistrationOverview id="r1" />);
    expect(await screen.findByText('Ready to decide')).toBeInTheDocument();
    expect(screen.getAllByText('Done')).toHaveLength(3);
  });

  it('never blocks the review on an automatic check: every step link is there while a check needs attention', async () => {
    render(<RegistrationOverview id="r1" />);
    await screen.findByText('Needs attention:');
    expect(screen.getByRole('link', { name: 'Start with the call-back' })).toBeEnabled();
    expect(screen.getByRole('link', { name: /4 Decide/ })).toBeInTheDocument();
  });

  it('shows the address check that passes with no area set, as the back end words it', async () => {
    overviewWith({ automaticChecks: [{ key: 'address', label: 'Address found. No area limit is set', ok: true }] });
    render(<RegistrationOverview id="r1" />);
    expect(await screen.findByText('Address found. No area limit is set')).toBeInTheDocument();
    expect(screen.queryByText('Needs attention:')).toBeNull();
  });

  it('shows a shimmer that says what is loading', () => {
    render(<RegistrationOverview id="r1" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the registration.');
  });

  it('says nothing was lost and offers Try again when the registration cannot be loaded', async () => {
    server.use(http.get('/api/bff/registrations/:id', () => HttpResponse.json({ error: 'x' }, { status: 500 })));
    render(<RegistrationOverview id="r1" />);
    expect(await screen.findByRole('heading', { level: 2, name: /We could not load this registration/ })).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been lost/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
