import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { MyServices } from './MyServices';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

describe('MyServices', () => {
  it('says how to add a service and passes axe', async () => {
    const { container } = render(<MyServices />);
    expect(await screen.findByRole('heading', { name: 'My services' })).toBeInTheDocument();
    expect(
      screen.getByText('To add a service, ask the shift lead. New services are added by invitation and checked.'),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('renders the three state texts from the list', async () => {
    server.use(
      http.get('/api/bff/reporter/services', () =>
        HttpResponse.json({
          services: [
            { id: 'a', name: 'UCR West', state: 'confirmed', recordedValue: 3, unitLabel: 'referrals', at: '2026-10-30T10:12:00Z', nextDue: '2026-10-30T12:00:00Z', pendingAcceptance: false },
            { id: 'b', name: 'UCR East', state: 'due', recordedValue: 1, unitLabel: 'referral', at: '2026-10-30T08:15:00Z', nextDue: '2026-10-30T12:00:00Z', replyBy: '2026-10-30T10:30:00Z', pendingAcceptance: false },
            { id: 'c', name: 'UCR North', state: 'paused', recordedValue: 0, unitLabel: 'referrals', at: '2026-10-30T08:00:00Z', nextDue: null, pendingAcceptance: false },
          ],
        }),
      ),
    );
    render(<MyServices />);
    expect(await screen.findByText('Confirmed 10:12 · Next due 12:00')).toBeInTheDocument();
    expect(screen.getByText('Due now · By 10:30')).toBeInTheDocument();
    expect(screen.getByText('Paused')).toBeInTheDocument();
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
