import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DECISION_OPEN } from '@/test/fixtures/registration';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { server } from '@/test/msw/server';
import { DecideStep } from './DecideStep';

const DECISION = '/api/bff/registrations/r1/decision';
beforeEach(() => resetRegistrationRequests());
const posts = () => seenRegistrationRequests.filter((r) => r.method === 'POST' && r.path === DECISION);

function decisionWith(missing: string[]) {
  server.use(
    http.get('/api/bff/registrations/:id/decision', () =>
      HttpResponse.json({ ...DECISION_OPEN, missing }, { headers: { 'Cache-Control': 'no-store' } }),
    ),
  );
}

describe('DecideStep', () => {
  it('keeps Approve aria-disabled and sends nothing while a check is missing, and names the missing check', async () => {
    decisionWith(['Call-back done']);
    const user = userEvent.setup();
    const { container } = render(<DecideStep id="r1" />);
    const approve = await screen.findByRole('button', { name: 'Approve (not yet available)' });
    expect(approve).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Call-back done');

    await user.click(approve);
    expect(posts()).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('enables Approve once nothing is missing, and approves on that press', async () => {
    decisionWith([]);
    const user = userEvent.setup();
    render(<DecideStep id="r1" />);
    const approve = await screen.findByRole('button', { name: 'Approve' });
    expect(approve).not.toHaveAttribute('aria-disabled', 'true');
    await user.click(approve);
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ action: 'approve' });
  });

  it('asks for a note before a send back, then sends it and says so', async () => {
    decisionWith([]);
    const user = userEvent.setup();
    render(<DecideStep id="r1" />);
    await user.click(await screen.findByRole('button', { name: 'Send back with a note' }));
    expect(await screen.findByText('Enter a note for the applicant')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Note to the applicant'), 'Please add an organisation address.');
    await user.click(screen.getByRole('button', { name: 'Send back with a note' }));
    expect(await screen.findByText('Sent back. The applicant sees your note.')).toBeInTheDocument();
    expect(posts()[0]?.body).toEqual({ action: 'send-back', note: 'Please add an organisation address.' });
  });
});
