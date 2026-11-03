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
const reportsFor = (id: string) => seenBffRequests.filter((r) => r.path === `/api/bff/reporter/services/${id}/report`);
const rowOf = (name: string) => screen.getByRole('heading', { name }).closest('li') as HTMLElement;

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

describe('GroupedUpdate', () => {
  it('shows one h1 with the service count, the reply-by tag and a card per service with its figure', async () => {
    render(<GroupedUpdate />);
    expect(await screen.findByRole('heading', { level: 1, name: '2 services' })).toBeInTheDocument();
    expect(screen.getByText('By 10:30')).toBeInTheDocument();
    const west = rowOf('UCR West');
    expect(within(west).getByText('3')).toBeInTheDocument();
    expect(within(west).getByText('referrals')).toBeInTheDocument();
    expect(within(west).getByText('at 08:15')).toBeInTheDocument();
    expect(within(rowOf('UCR East')).getByText('1')).toBeInTheDocument();
    expect(screen.getByText('Each service is confirmed on its own line in the record.')).toBeInTheDocument();
  });

  it('has one primary action and says the services are loading with the shared skeleton', async () => {
    render(<GroupedUpdate />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading your services.');
    await screen.findByRole('button', { name: 'Both still right (3 and 1)' });
    const primaries = document.querySelectorAll('[data-variant="primary"]');
    expect(primaries).toHaveLength(1);
  });

  it('confirms both services in one batch with "Both still right (3 and 1)" and shows both lines', async () => {
    const { container } = render(<GroupedUpdate />);
    await userEvent.click(await screen.findByRole('button', { name: 'Both still right (3 and 1)' }));
    expect(await screen.findByText('UCR West 3 referrals · 10:12')).toBeInTheDocument();
    expect(screen.getByText('UCR East 1 referral · 10:12')).toBeInTheDocument();
    expect(within(rowOf('UCR West')).getByText('Confirmed 10:12')).toBeInTheDocument();
    expect(within(rowOf('UCR East')).getByText('Confirmed 10:12')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Both still right/ })).toBeNull();
    expect(batchBodies()).toEqual([
      { items: [{ serviceId: 'svc-west', kind: 'confirm' }, { serviceId: 'svc-east', kind: 'confirm' }] },
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('confirming only UCR West leaves UCR East "Waiting", sends no item for it, and drops "Both"', async () => {
    render(<GroupedUpdate />);
    await screen.findByRole('heading', { name: 'UCR West' });
    await userEvent.click(within(rowOf('UCR West')).getByRole('button', { name: 'Still right' }));
    await waitFor(() => expect(batchBodies()).toHaveLength(1));
    expect(batchBodies()[0]).toEqual({ items: [{ serviceId: 'svc-west', kind: 'confirm' }] });
    expect(await within(rowOf('UCR East')).findByText('Waiting')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Both still right/ })).toBeNull();
  });

  it('Change opens the stepper inline on that service and leaves the other card in place', async () => {
    const { container } = render(<GroupedUpdate />);
    await screen.findByRole('heading', { name: 'UCR East' });
    await userEvent.click(within(rowOf('UCR East')).getByRole('button', { name: 'Change' }));
    const east = rowOf('UCR East');
    expect(await within(east).findByRole('textbox', { name: 'New number for UCR East' })).toBeInTheDocument();
    expect(within(east).getByText(/usual range 0 to 8/)).toBeInTheDocument();
    expect(within(east).getByRole('button', { name: 'Send new number' })).toBeDisabled();
    expect(within(rowOf('UCR West')).getByRole('button', { name: 'Still right' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: '2 services' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('sends the new number for that service on its own report, with its own Idempotency-Key, and shows the line', async () => {
    render(<GroupedUpdate />);
    await screen.findByRole('heading', { name: 'UCR East' });
    await userEvent.click(within(rowOf('UCR East')).getByRole('button', { name: 'Change' }));
    const east = rowOf('UCR East');
    const plus = await within(east).findByRole('button', { name: 'Increase by one' });
    await userEvent.click(plus);
    await userEvent.click(plus);
    await userEvent.click(plus);
    await userEvent.click(within(east).getByRole('button', { name: 'Send new number' }));
    expect(await screen.findByText('UCR East 2 referral · 10:12')).toBeInTheDocument();
    expect(reportsFor('svc-east')).toHaveLength(1);
    expect(reportsFor('svc-east')[0].body).toEqual({ kind: 'number', value: 2 });
    expect(reportsFor('svc-east')[0].idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    expect(within(rowOf('UCR East')).getByText('Confirmed 10:12')).toBeInTheDocument();
    expect(within(rowOf('UCR East')).queryByRole('textbox')).toBeNull();
    expect(batchBodies()).toHaveLength(0);
  });

  it('Cancel closes the inline stepper and sends nothing', async () => {
    render(<GroupedUpdate />);
    await screen.findByRole('heading', { name: 'UCR West' });
    await userEvent.click(within(rowOf('UCR West')).getByRole('button', { name: 'Change' }));
    await userEvent.click(await within(rowOf('UCR West')).findByRole('button', { name: 'Cancel' }));
    expect(within(rowOf('UCR West')).queryByRole('textbox')).toBeNull();
    expect(within(rowOf('UCR West')).getByRole('button', { name: 'Change' })).toBeInTheDocument();
    expect(reportsFor('svc-west')).toHaveLength(0);
  });

  it('the inline panel can also say a service is closed to referrals', async () => {
    render(<GroupedUpdate />);
    await screen.findByRole('heading', { name: 'UCR West' });
    await userEvent.click(within(rowOf('UCR West')).getByRole('button', { name: 'Change' }));
    await userEvent.click(await within(rowOf('UCR West')).findByRole('button', { name: 'We are closed to referrals' }));
    await waitFor(() => expect(reportsFor('svc-west')).toHaveLength(1));
    expect(reportsFor('svc-west')[0].body).toEqual({ kind: 'closed' });
  });

  it('flags a figure outside the usual range on that service line and asks to send it again', async () => {
    render(<GroupedUpdate />);
    await screen.findByRole('heading', { name: 'UCR West' });
    await userEvent.click(within(rowOf('UCR West')).getByRole('button', { name: 'Change' }));
    const box = await within(rowOf('UCR West')).findByRole('textbox', { name: 'New number for UCR West' });
    await userEvent.type(box, '9');
    await userEvent.click(within(rowOf('UCR West')).getByRole('button', { name: 'Send new number' }));
    expect(await within(rowOf('UCR West')).findByText('That is outside your usual range (0 to 8). Send it again to confirm.')).toBeInTheDocument();
    await userEvent.click(within(rowOf('UCR West')).getByRole('button', { name: 'Send new number' }));
    await waitFor(() => expect(reportsFor('svc-west')).toHaveLength(2));
    expect(reportsFor('svc-west')[1].body).toEqual({ kind: 'number', value: 9, confirmOutOfRange: true });
  });

  it('sends the batch with an Idempotency-Key', async () => {
    render(<GroupedUpdate />);
    await userEvent.click(await screen.findByRole('button', { name: 'Both still right (3 and 1)' }));
    await screen.findByText('UCR West 3 referrals · 10:12');
    const batch = seenBffRequests.find((r) => r.path === '/api/bff/reporter/reports/batch');
    expect(batch?.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });

  it('says a service that must send a number was not confirmed, on its own line, and does not show it as done', async () => {
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
    expect(within(rowOf('UCR East')).getByText('UCR East needs its number. Use Change to send it.')).toBeInTheDocument();
    expect(within(rowOf('UCR West')).queryByText(/needs its number/)).toBeNull();
    expect(within(rowOf('UCR East')).getByRole('button', { name: 'Change' })).toBeInTheDocument();
  });

  it('says a service the batch did not answer could not be recorded, on its own line', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(
      http.post('/api/bff/reporter/reports/batch', () =>
        HttpResponse.json({ results: [{ serviceId: 'svc-west', result: 'recorded', at: '2026-10-30T10:12:00Z' }, { serviceId: 'svc-east', result: 'failed' }] }),
      ),
    );
    render(<GroupedUpdate />);
    await userEvent.click(await screen.findByRole('button', { name: 'Both still right (3 and 1)' }));
    expect(await within(rowOf('UCR East')).findByText('We could not record that. Try again.')).toBeInTheDocument();
    expect(within(rowOf('UCR West')).queryByText('We could not record that. Try again.')).toBeNull();
  });

  it('says the services could not be loaded when the back end fails', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<GroupedUpdate />);
    expect(await screen.findByText('We could not load your services. Try again shortly.')).toBeInTheDocument();
  });
});
