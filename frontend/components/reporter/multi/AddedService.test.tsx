import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { AddedService } from './AddedService';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  resetReporterRequests();
});

describe('AddedService', () => {
  it('shows Waiting for you, the name in the heading, the question, and the check', async () => {
    const { container } = render(<AddedService serviceId="svc-north" serviceName="UCR North" />);
    const tag = screen.getByText('Waiting for you');
    expect(tag.closest('[data-variant]')).toHaveAttribute('data-variant', 'waiting');
    expect(screen.getByRole('heading', { name: 'UCR North has been added' })).toBeInTheDocument();
    expect(screen.getByText('The shift lead added UCR North to your account. Do you look after it?')).toBeInTheDocument();
    expect(screen.getByText('We check this with the service before it goes live. Your other services are not affected.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('answers Yes, and goes back to My services', async () => {
    render(<AddedService serviceId="svc-north" serviceName="UCR North" />);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, I look after UCR North' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/services'));
    expect(seenBffRequests.find((r) => r.path.endsWith('/accept'))?.body).toEqual({ accept: true });
  });

  it('answers No, and goes back to My services', async () => {
    render(<AddedService serviceId="svc-north" serviceName="UCR North" />);
    await userEvent.click(screen.getByRole('button', { name: 'No, this is not me' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/services'));
    expect(seenBffRequests.find((r) => r.path.endsWith('/accept'))?.body).toEqual({ accept: false });
  });

  it('stays here and says the answer was not saved when the back end refuses it', async () => {
    server.use(http.post('/api/bff/reporter/services/:serviceId/accept', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<AddedService serviceId="svc-north" serviceName="UCR North" />);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, I look after UCR North' }));
    expect(await screen.findByText('We could not save your answer. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
