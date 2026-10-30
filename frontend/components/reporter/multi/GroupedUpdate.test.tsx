import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { GroupedUpdate } from './GroupedUpdate';

vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const batchBodies = () => seenBffRequests.filter((r) => r.path === '/api/bff/reporter/reports/batch').map((r) => r.body);

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

describe('GroupedUpdate', () => {
  it('confirms both services in one batch with "Both still right (3 and 1)" and shows both lines', async () => {
    const { container } = render(<GroupedUpdate />);
    await userEvent.click(await screen.findByRole('button', { name: 'Both still right (3 and 1)' }));
    expect(await screen.findByText('UCR West 3 referrals · 10:12')).toBeInTheDocument();
    expect(screen.getByText('UCR East 1 referral · 10:12')).toBeInTheDocument();
    expect(batchBodies()).toEqual([
      { items: [{ serviceId: 'svc-west', kind: 'confirm' }, { serviceId: 'svc-east', kind: 'confirm' }] },
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('confirming only UCR West leaves UCR East "Waiting" and sends no item for it', async () => {
    render(<GroupedUpdate />);
    const rows = await screen.findAllByRole('listitem');
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Still right' }));
    await waitFor(() => expect(batchBodies()).toHaveLength(1));
    expect(batchBodies()[0]).toEqual({ items: [{ serviceId: 'svc-west', kind: 'confirm' }] });
    const east = screen.getByText('UCR East').closest('li') as HTMLElement;
    expect(within(east).getByText('Waiting')).toBeInTheDocument();
  });

  it('Change UCR East shows the banner, the position, and names the service in the thanks line', async () => {
    render(<GroupedUpdate />);
    const rows = await screen.findAllByRole('listitem');
    await userEvent.click(within(rows[1]).getByRole('button', { name: 'Change' }));
    expect(await screen.findByRole('heading', { name: 'Updating UCR East' })).toBeInTheDocument();
    expect(screen.getByText('UCR East · 1 of 2')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 1' }));
    expect(await screen.findByText('UCR East 1 referral · 10:12')).toBeInTheDocument();
  });

  it('sends the batch with an Idempotency-Key, and a change with its own', async () => {
    render(<GroupedUpdate />);
    await userEvent.click(await screen.findByRole('button', { name: 'Both still right (3 and 1)' }));
    await screen.findByText('UCR West 3 referrals · 10:12');
    const batch = seenBffRequests.find((r) => r.path === '/api/bff/reporter/reports/batch');
    expect(batch?.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });

  it('shows London clock time for the due-by line and the confirmed lines', async () => {
    render(<GroupedUpdate />);
    expect(await screen.findByText('Update by 10:30')).toBeInTheDocument();
  });

  it('says a service that must send a number was not confirmed, and does not show it as done', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(
      http.post('/api/bff/reporter/reports/batch', () =>
        HttpResponse.json({ results: [{ serviceId: 'svc-west', result: 'recorded', at: '2026-10-30T10:12:00Z' }, { serviceId: 'svc-east', result: 'sendNumber', reason: 'stale' }] }),
      ),
    );
    render(<GroupedUpdate />);
    await userEvent.click(await screen.findByRole('button', { name: 'Both still right (3 and 1)' }));
    expect(await screen.findByText('UCR West 3 referrals · 10:12')).toBeInTheDocument();
    expect(screen.queryByText('UCR East 1 referral · 10:12')).toBeNull();
    expect(screen.getByText('UCR East needs its number. Use Change to send it.')).toBeInTheDocument();
  });

  it('says the services could not be loaded when the back end fails', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<GroupedUpdate />);
    expect(await screen.findByText('We could not load your services. Try again shortly.')).toBeInTheDocument();
  });
});
