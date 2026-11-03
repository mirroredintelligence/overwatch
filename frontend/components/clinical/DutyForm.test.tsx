import { render, screen, waitFor, within } from '@testing-library/react';
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
    render(<DutyForm available={2} waiting={1} presence={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Busy' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save status' }));
    await waitFor(() => expect(seenClinical.filter((c) => c.path === '/api/bff/clinical/presence')).toHaveLength(1));
    expect(seenClinical.find((c) => c.path === '/api/bff/clinical/presence')?.body).toEqual({ presence: 'busy' });
  });

  it('starts where the clinician left it: the saved presence is chosen, and nothing is chosen when none is saved', () => {
    const { unmount } = render(<DutyForm available={2} waiting={1} presence="busy" />);
    expect(screen.getByRole('button', { name: 'Busy' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Available' })).toHaveAttribute('aria-pressed', 'false');
    unmount();
    render(<DutyForm available={2} waiting={1} presence={null} />);
    expect(screen.getByRole('button', { name: 'Busy' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('You have not set your status.')).toBeInTheDocument();
  });

  it('warns before saving Away that unfinished requests go back to the queue', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<DutyForm available={2} waiting={1} presence={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Away' }));
    expect(screen.getByText('Your unfinished requests go back to the queue.')).toBeInTheDocument();
    expect(seenClinical.filter((c) => c.path === '/api/bff/clinical/presence')).toHaveLength(0);
  });

  it('shows the right-now figures as numbers with their words, and links to the queue', () => {
    render(<DutyForm available={2} waiting={1} presence={null} />);
    const now = screen.getByRole('region', { name: 'Right now' });
    expect(within(now).getByText('1')).toBeInTheDocument();
    expect(within(now).getByText('request waiting')).toBeInTheDocument();
    expect(within(now).getByText('2')).toBeInTheDocument();
    expect(within(now).getByText('clinical advisors available now')).toBeInTheDocument();
    expect(within(now).getByRole('link', { name: 'Open the queue' })).toHaveAttribute('href', '/clinical/requests');
    expect(screen.getByText('Advisors see how many of you are available. They see your name only after you take a request.')).toBeInTheDocument();
  });

  it('says what each status means in the words the board uses, as the description of its button', () => {
    render(<DutyForm available={2} waiting={1} presence={null} />);
    expect(screen.getByRole('button', { name: 'Available' })).toHaveAccessibleDescription('Advisors can send you requests now.');
    expect(screen.getByRole('button', { name: 'Busy' })).toHaveAccessibleDescription('You finish what you are doing first. Requests wait in the queue.');
    expect(screen.getByRole('button', { name: 'Away' })).toHaveAccessibleDescription('You will not get alerts.');
  });

  it('says the counts could not be read rather than showing zero', () => {
    render(<DutyForm available={null} waiting={null} presence={null} />);
    expect(screen.getByText('The counts could not be read.')).toBeInTheDocument();
    expect(screen.queryByText(/0 request/)).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<DutyForm available={2} waiting={1} presence="available" />);
    expect(screen.getByRole('button', { name: 'Save status' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
