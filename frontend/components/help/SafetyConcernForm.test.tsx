import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SafetyConcernForm } from './SafetyConcernForm';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh: vi.fn(), replace: vi.fn() }) }));

const sent: unknown[] = [];

beforeEach(() => {
  sent.length = 0;
  server.use(http.post('/api/bff/help/safety-concerns', async ({ request }) => {
    sent.push(await request.json());
    return HttpResponse.json({ reference: 'SC-0192' });
  }));
});

describe('SafetyConcernForm', () => {
  it('shows both required errors together in an error summary, and sends nothing', async () => {
    render(<SafetyConcernForm />);
    await userEvent.click(screen.getByRole('button', { name: 'Send to the clinical safety officer' }));
    const summary = screen.getByRole('alert');
    expect(within(summary).getByText('Choose what it is about.')).toBeInTheDocument();
    expect(within(summary).getByText('Tell us what happened.')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('refuses the 281st character and counts to 280', async () => {
    render(<SafetyConcernForm />);
    fireEvent.change(screen.getByLabelText('What happened?'), { target: { value: 'x'.repeat(281) } });
    expect(screen.getByText('281 of 280')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Send to the clinical safety officer' }));
    expect(screen.getByText('Keep it to 280 characters')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('sends a valid concern and confirms it with the reference', async () => {
    render(<SafetyConcernForm />);
    await userEvent.click(screen.getByRole('button', { name: 'Out-of-date criteria' }));
    await userEvent.type(screen.getByLabelText('What happened?'), 'Criteria still list a closed ward');
    await userEvent.click(screen.getByRole('button', { name: 'Send to the clinical safety officer' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ category: 'out-of-date-criteria', text: 'Criteria still list a closed ward' });
    expect(await screen.findByRole('heading', { name: 'Concern SC-0192 sent' })).toBeInTheDocument();
    expect(screen.getByText('A clinical safety officer will review it. You will be told when it has been looked at.')).toBeInTheDocument();
  });

  it('warns, without blocking, when the text looks like patient details', async () => {
    render(<SafetyConcernForm />);
    await userEvent.type(screen.getByLabelText('What happened?'), 'Patient at DT4 8XX');
    expect(screen.getByText('This looks like it may contain patient details. Please remove them.')).toBeInTheDocument();
  });

  it('shows the warning about someone at risk before the form', () => {
    render(<SafetyConcernForm />);
    expect(screen.getByText('If someone is at risk now, phone the SPOA or follow local procedure first.')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<SafetyConcernForm />);
    expect(screen.getByRole('button', { name: 'Send to the clinical safety officer' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
