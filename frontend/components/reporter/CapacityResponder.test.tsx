import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parseLinkView, type LinkView } from '@/lib/links/model';
import { runAxe } from '@/test/a11y';
import { EMPTY_VIEW, LINK, RECORDED_VIEW, csrfFor } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { CapacityResponder } from './CapacityResponder';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const viewOf = (token: string, fields: Record<string, unknown> = RECORDED_VIEW): LinkView =>
  parseLinkView({ ...fields, csrfToken: csrfFor(token) });

function renderFor(token: string, fields?: Record<string, unknown>) {
  return render(<CapacityResponder token={token} view={viewOf(token, fields)} />);
}

beforeEach(() => {
  resetLinkRequests();
  push.mockClear();
});

describe('CapacityResponder with a figure on record', () => {
  it('asks whether the figure is still right, with the figure and its time', async () => {
    const { container } = renderFor(LINK.recorded);
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('We have 3 referrals in the next 2 hrs, as of 08:15. Still right?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toHaveAttribute('data-el', 'REP-LINK-CONFIRM-BTN');
    expect(screen.getByText('No login. This link works once and expires at 10:30. Next update due 12:00.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('makes no POST while it renders', () => {
    renderFor(LINK.recorded);
    expect(seenBffPosts).toHaveLength(0);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('posts a confirm with the CSRF header, then opens the thank-you page with the figure and its time', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts).toEqual([{ token: LINK.recorded, body: { action: 'confirm' }, csrf: csrfFor(LINK.recorded) }]);
    const href = String(push.mock.calls[0]?.[0]);
    expect(new URL(href, 'https://x.test').pathname).toBe(`/l/${LINK.recorded}/thanks`);
    expect(new URL(href, 'https://x.test').searchParams.get('at')).toBe('2026-10-23T09:12:00Z');
  });

  it('steps up to 4, then sends that number', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(screen.getByRole('textbox', { name: 'Referrals in the next 2 hrs' })).toHaveValue('4');
    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 4 });
  });

  it('sends "closed" for a service that is closed to referrals', async () => {
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'We are closed to referrals' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'closed' });
  });

  it('shows the out-of-range message for a figure outside the usual range, and sends it again only as a confirmed figure', async () => {
    renderFor(LINK.recorded);
    const stepper = screen.getByRole('textbox', { name: 'Referrals in the next 2 hrs' });
    await userEvent.clear(stepper);
    await userEvent.type(stepper, '9');
    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    expect(
      await screen.findByText(
        'That is outside your usual range of 0 to 8. Check it and press Send new number again to confirm.',
      ),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 9, confirmOutOfRange: true });
  });

  it('says to send the number when the back end will not take a confirm, and records nothing', async () => {
    renderFor(LINK.stale);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('Please send the number.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('says to wait when the tenant’s link budget is used up', async () => {
    renderFor(LINK.limited);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('Too many tries. Wait a few minutes, then try again.')).toBeInTheDocument();
  });

  it('says it could not record the answer, and offers to try again, when the request fails', async () => {
    server.use(http.post('/api/bff/links/:token', () => HttpResponse.json({}, { status: 503 })));
    renderFor(LINK.recorded);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('We could not record that. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('shows the expired message when the link is used or expires after the page loaded', async () => {
    renderFor(LINK.recorded);
    server.use(http.post('/api/bff/links/:token', () => HttpResponse.json({ state: 'used' }, { status: 410 })));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

});

describe('CapacityResponder with no figure yet', () => {
  const EMPTY = EMPTY_VIEW as unknown as Record<string, unknown>;

  it('asks how many can be taken, with the send button disabled until a number is chosen', async () => {
    const { container } = renderFor(LINK.empty, EMPTY);
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('How many referrals can you take in the next 2 hrs?')).toBeInTheDocument();
    const send = screen.getByRole('button', { name: 'Choose a number to send' });
    expect(send).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Referrals in the next 2 hrs' })).toHaveValue('');
    expect(screen.getByText('This link works once and expires at 08:30. Next update due 10:00.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('enables the button, and reads "Send new number", once a number is chosen', async () => {
    renderFor(LINK.empty, EMPTY);
    await userEvent.type(screen.getByRole('textbox', { name: 'Referrals in the next 2 hrs' }), '4');
    const send = await screen.findByRole('button', { name: 'Send new number' });
    expect(send).toBeEnabled();
    await userEvent.click(send);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenBffPosts.at(-1)?.body).toEqual({ action: 'number', value: 4 });
  });
});

describe('CapacityResponder accessibility', () => {
  it('labels the stepper, and names every button with words', () => {
    renderFor(LINK.recorded);
    expect(screen.getByRole('textbox', { name: 'Referrals in the next 2 hrs' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Decrease by one' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Increase by one' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'We are closed to referrals' })).toBeInTheDocument();
  });
});
