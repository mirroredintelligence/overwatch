import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { runAxe } from '@/test/a11y';
import { DECISION_READY } from '@/test/fixtures/registration';
import { resetRegistrationRequests } from '@/test/msw/handlers/registrations';
import { server } from '@/test/msw/server';
import { GoLive } from './GoLive';

beforeEach(() => resetRegistrationRequests());

function decisionWith(decision: unknown) {
  server.use(http.get('/api/bff/registrations/:id/decision', () => HttpResponse.json(decision as Record<string, unknown>)));
}

describe('GoLive', () => {
  it('keeps Set live disabled until the test is answered, then enables it', async () => {
    decisionWith({ ...DECISION_READY, test: { sentAt: '2026-10-30T15:02:00Z' } });
    const { unmount } = render(<GoLive id="r1" />);
    expect(await screen.findByRole('button', { name: 'Set live' })).toBeDisabled();
    expect(screen.getByText('Test notification sent 15:02')).toBeInTheDocument();
    unmount();

    decisionWith(DECISION_READY);
    render(<GoLive id="r1" />);
    expect(await screen.findByRole('button', { name: 'Set live' })).toBeEnabled();
    expect(screen.getByText('Test answered 15:03 from the registered phone')).toBeInTheDocument();
  });

  it('shows who approved, the board preview and the record, and is accessible', async () => {
    decisionWith(DECISION_READY);
    const { container } = render(<GoLive id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Go live: UCR East' })).toBeInTheDocument();
    expect(screen.getByText('Approved by Service manager and Clinical lead')).toBeInTheDocument();
    expect(screen.getByText('Registration record')).toBeInTheDocument();
    expect(screen.getByText('Submitted by Duty manager')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
