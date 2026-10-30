import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { clinicalBffHandlers, resetClinicalBff, seenBff } from '@/test/msw/handlers/clinical';
import { server } from '@/test/msw/server';
import { CaseView } from './CaseView';

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh, replace: vi.fn() }) }));

const request = { id: 'req-4821', urgency: 'now' as const, why: 'borderline-criteria', caseId: 'case-4821' };
const advised = () => seenBff.filter((c) => c.path.endsWith('/advice'));

describe('CaseView', () => {
  it('shows the case number, and says the case details are not on this screen yet', () => {
    resetClinicalBff();
    render(<CaseView request={request} />);
    expect(screen.getByRole('heading', { name: 'Case 4821' })).toBeInTheDocument();
    expect(screen.getByText('The case details are not on this screen yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send advice' })).toBeInTheDocument();
  });

  it('asks for an advice choice before sending, and sends nothing', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<CaseView request={request} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    expect(screen.getByText('Choose what you advise.')).toBeInTheDocument();
    expect(advised()).toHaveLength(0);
  });

  it('blocks a note of 281 characters with its message, and sends nothing', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<CaseView request={request} />);
    await userEvent.click(screen.getByRole('button', { name: 'Go ahead with the service' }));
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: 'x'.repeat(281) } });
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    expect(screen.getByText('Keep the note to 280 characters')).toBeInTheDocument();
    expect(advised()).toHaveLength(0);
  });

  it('posts a valid advice and then shows the confirmation', async () => {
    resetClinicalBff();
    server.use(...clinicalBffHandlers);
    render(<CaseView request={request} />);
    await userEvent.click(screen.getByRole('button', { name: 'Go ahead with the service' }));
    await userEvent.click(screen.getByRole('button', { name: 'Within criteria on my judgement' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send advice' }));
    await waitFor(() => expect(advised()).toHaveLength(1));
    expect(advised()[0]?.body).toEqual(expect.objectContaining({ advice: 'go-ahead', reason: 'within-criteria-on-judgement' }));
    expect(await screen.findByRole('heading', { name: 'Advice sent' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Next request' })).toHaveAttribute('href', '/clinical/requests');
    expect(screen.getByRole('button', { name: 'Go off duty' })).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<CaseView request={request} />);
    expect(screen.getByRole('button', { name: 'Send advice' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
