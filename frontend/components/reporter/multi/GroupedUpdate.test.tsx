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
});
