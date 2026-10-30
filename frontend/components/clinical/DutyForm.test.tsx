import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { clinicalBffHandlers, resetClinicalBff, seenBff as seenClinical } from '@/test/msw/handlers/clinical';
import { server } from '@/test/msw/server';
import { DutyForm } from './DutyForm';

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh, replace: vi.fn() }) }));

describe('DutyForm', () => {
  it('saves the chosen presence', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<DutyForm available={2} waiting={1} />);
    await userEvent.click(screen.getByRole('button', { name: 'Busy' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save status' }));
    await waitFor(() => expect(seenClinical.filter((c) => c.path === '/api/bff/clinical/presence')).toHaveLength(1));
    expect(seenClinical.find((c) => c.path === '/api/bff/clinical/presence')?.body).toEqual({ presence: 'busy' });
  });

  it('warns before saving Away that unfinished requests go back to the queue', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<DutyForm available={2} waiting={1} />);
    await userEvent.click(screen.getByRole('button', { name: 'Away' }));
    expect(screen.getByText('Your unfinished requests go back to the queue.')).toBeInTheDocument();
    expect(seenClinical.filter((c) => c.path === '/api/bff/clinical/presence')).toHaveLength(0);
  });

  it('says how many advisors are available and how many requests are waiting', () => {
    render(<DutyForm available={2} waiting={1} />);
    expect(screen.getByText('1 request waiting')).toBeInTheDocument();
    expect(screen.getByText('2 clinical advisors available now')).toBeInTheDocument();
    expect(screen.getByText('Advisors see how many of you are available. They see your name only after you take a request.')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<DutyForm available={2} waiting={1} />);
    expect(screen.getByRole('button', { name: 'Save status' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
