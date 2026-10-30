import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { ServiceCover } from './ServiceCover';

vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  resetReporterRequests();
});

describe('ServiceCover', () => {
  it('asks for a mobile number and gives the mobile error without one', async () => {
    const { container } = render(<ServiceCover serviceId="svc-east" serviceName="UCR East" />);
    expect(screen.getByRole('heading', { name: 'Cover for UCR East' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Hand over UCR East' }));
    expect(await screen.findByText('Enter a UK mobile number, like 07700 900123')).toBeInTheDocument();
    expect(seenBffRequests.some((r) => r.path.endsWith('/cover'))).toBe(false);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('posts the number and the until choice', async () => {
    render(<ServiceCover serviceId="svc-east" serviceName="UCR East" />);
    await userEvent.type(screen.getByLabelText('Cover mobile number'), '07700 900123');
    await userEvent.click(screen.getByRole('radio', { name: 'This week' }));
    await userEvent.click(screen.getByRole('button', { name: 'Hand over UCR East' }));
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/services/svc-east/cover')).toBe(true));
    expect(seenBffRequests.find((r) => r.path.endsWith('/cover'))?.body).toEqual({ phone: '07700 900123', until: 'this-week' });
  });
});
