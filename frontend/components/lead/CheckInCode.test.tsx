import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { CHECKIN_CODE, resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { CheckInCode } from './CheckInCode';

// The printed check-in code of a service (DEC-1346): made on a press, drawn from the matrix, printed, replaced.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=csrf-for-the-code; path=/';
});

describe('CheckInCode', () => {
  it('makes nothing until the button is pressed, and says a new code stops the printed one', () => {
    render(<CheckInCode serviceId="s-virtual-ward" />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText(/Making a new\s+code stops the one already printed/)).toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('makes the code, draws it with the service name and the address, and offers Print and a new code', async () => {
    const user = userEvent.setup();
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    const { container } = render(<CheckInCode serviceId="s-virtual-ward" />);

    await user.click(byEl('LEAD-CHECKIN-MAKE-BTN'));

    expect(await screen.findByRole('img', { name: 'QR code to check in to UCR West' })).toBeInTheDocument();
    expect(container.querySelector('path')?.getAttribute('d')).toMatch(/^M0 0h1v1h-1z/);
    expect(screen.getByText(CHECKIN_CODE.url)).toBeInTheDocument();
    expect(seenLeadPosts.at(-1)).toMatchObject({ path: '/api/bff/lead/services/s-virtual-ward/checkin-code' });
    expect(seenLeadPosts.at(-1)?.csrf).toBe('csrf-for-the-code');
    expect(byEl('LEAD-CHECKIN-MAKE-BTN')).toHaveTextContent('Make a new code');

    await user.click(byEl('LEAD-CHECKIN-PRINT-BTN'));
    expect(print).toHaveBeenCalledOnce();
    print.mockRestore();
  });

  it('says the code could not be made when the answer is not a code', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/lead/services/:id/checkin-code', () => HttpResponse.json({ nonsense: true })));
    render(<CheckInCode serviceId="s-virtual-ward" />);

    await user.click(byEl('LEAD-CHECKIN-MAKE-BTN'));

    expect(await screen.findByRole('alert')).toHaveTextContent('The code could not be made. Try again.');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('says so when the press fails', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/lead/services/:id/checkin-code', () => HttpResponse.json({}, { status: 500 })));
    render(<CheckInCode serviceId="s-virtual-ward" />);

    await user.click(byEl('LEAD-CHECKIN-MAKE-BTN'));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('has no accessibility violations with the code showing', async () => {
    const user = userEvent.setup();
    const { container } = render(<CheckInCode serviceId="s-virtual-ward" />);
    await user.click(byEl('LEAD-CHECKIN-MAKE-BTN'));
    await screen.findByRole('img');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
