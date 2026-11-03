import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CriteriaStatus } from './CriteriaStatus';

describe('CriteriaStatus', () => {
  it('while waiting, says the live version stays live until the new one is approved, with the sent time', async () => {
    render(<CriteriaStatus version={3} liveVersion={2} sentAt="2026-11-03T14:20:00Z" waiting />);
    const status = screen.getByRole('status');
    expect(within(status).getByRole('heading', { level: 2, name: 'Waiting for approval' })).toBeInTheDocument();
    expect(within(status).getByText('Version 2 stays live until someone else approves version 3.')).toBeInTheDocument();
    expect(within(status).getByText('Sent by you at 14:20')).toBeInTheDocument();
    expect(within(status).getByText('Waiting for a second approver')).toBeInTheDocument();
    expect(within(status).getByText('Live for advisors')).toBeInTheDocument();
    expect(within(status).getByText('You will be told when they have, or if they send it back with a note.')).toBeInTheDocument();
    expect(await runAxe(status)).toHaveNoViolations();
  });

  it('shows the sent step without a time when none is given', () => {
    render(<CriteriaStatus version={3} liveVersion={2} waiting />);
    expect(screen.getByText('Sent by you')).toBeInTheDocument();
  });

  it('once live, says the version advisors see now', async () => {
    render(<CriteriaStatus version={3} liveVersion={3} waiting={false} />);
    const status = screen.getByRole('status');
    expect(within(status).getByRole('heading', { level: 2, name: 'Live' })).toBeInTheDocument();
    expect(within(status).getByText('Advisors see version 3.')).toBeInTheDocument();
    expect(await runAxe(status)).toHaveNoViolations();
  });
});
