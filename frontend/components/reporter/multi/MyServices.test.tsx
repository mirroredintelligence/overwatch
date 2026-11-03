import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { MyServices } from './MyServices';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const THREE = [
  { id: 'a', name: 'UCR West', state: 'confirmed', recordedValue: 3, unitLabel: 'referrals', at: '2026-10-30T10:12:00Z', nextDue: '2026-10-30T12:00:00Z', pendingAcceptance: false },
  { id: 'b', name: 'UCR East', state: 'due', recordedValue: 1, unitLabel: 'referral', at: '2026-10-30T08:15:00Z', nextDue: '2026-10-30T12:00:00Z', replyBy: '2026-10-30T10:30:00Z', pendingAcceptance: false },
  { id: 'c', name: 'Virtual ward', state: 'paused', recordedValue: 0, unitLabel: 'referrals', at: '2026-10-30T08:00:00Z', nextDue: null, pendingAcceptance: false },
];

describe('MyServices', () => {
  it('shows a loading line in words while the list comes', () => {
    render(<MyServices />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading your services.');
  });

  it('says how to add a service and passes axe', async () => {
    const { container } = render(<MyServices />);
    expect(await screen.findByRole('heading', { name: 'My services' })).toBeInTheDocument();
    expect(
      screen.getByText('To add a service, ask the shift lead. New services are added by invitation and checked.'),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says you have no services yet, with the one next step, and no empty list', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ services: [] })));
    const { container } = render(<MyServices />);
    expect(await screen.findByRole('heading', { name: 'You have no services yet' })).toBeInTheDocument();
    expect(screen.getByText('To add one, ask the shift lead. New services are added by invitation and checked.')).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows each state as a shape and a word: confirmed with its time, due now with its reply time, paused', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ services: THREE })));
    render(<MyServices />);
    const confirmed = await screen.findByText('Confirmed 10:12');
    expect(confirmed.closest('[data-variant]')).toHaveAttribute('data-variant', 'confirmed');
    expect(screen.getByText('Next due 12:00')).toBeInTheDocument();
    const due = screen.getByText('Due now');
    expect(due.closest('[data-variant]')).toHaveAttribute('data-variant', 'due');
    expect(screen.getByText('Reply by 10:30')).toBeInTheDocument();
    const paused = screen.getByText('Paused');
    expect(paused.closest('[data-variant]')).toHaveAttribute('data-variant', 'paused');
    expect(paused.closest('li')).toHaveAttribute('data-state', 'paused');
  });

  it('gives only the due-now card an Update button, and it goes to that one service', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ services: THREE })));
    render(<MyServices />);
    expect(await screen.findByRole('link', { name: 'Update UCR East' })).toHaveAttribute('href', '/app/respond/b');
    expect(screen.getAllByRole('link', { name: /^Update/ })).toHaveLength(1);
  });

  it('passes axe with the three cards', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ services: THREE })));
    const { container } = render(<MyServices />);
    await screen.findByText('Confirmed 10:12');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows nothing that is not on record: a service never reported has no clock time', async () => {
    server.use(
      http.get('/api/bff/reporter/services', () =>
        HttpResponse.json({ services: [{ id: 'a', name: 'UCR West', state: 'confirmed', recordedValue: null, unitLabel: 'referrals', at: null, nextDue: null, pendingAcceptance: false }] }),
      ),
    );
    render(<MyServices />);
    expect(await screen.findByText('Confirmed')).toBeInTheDocument();
  });

  it('says the services could not be loaded when the back end fails, and not that there are none', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<MyServices />);
    expect(await screen.findByText('We could not load your services. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'You have no services yet' })).not.toBeInTheDocument();
  });

  it('links a service the lead added to the page that asks the reporter, by its id and name', async () => {
    server.use(
      http.get('/api/bff/reporter/services', () =>
        HttpResponse.json({ services: [{ id: 'a b', name: 'UCR West', state: 'confirmed', recordedValue: 1, unitLabel: 'referral', at: null, nextDue: null, pendingAcceptance: true }] }),
      ),
    );
    render(<MyServices />);
    expect(await screen.findByRole('link', { name: 'Check the new service' })).toHaveAttribute('href', '/app/services/a%20b/added');
  });
});
