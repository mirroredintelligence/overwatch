import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LINK } from '@/test/fixtures/links';
import { resetLinkRequests, seenBffRenews } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { LinkExpired } from './LinkExpired';

beforeEach(() => resetLinkRequests());

describe('LinkExpired', () => {
  it('says the link can no longer be used, and what to do instead', async () => {
    const { container } = render(<LinkExpired token={LINK.expired} />);
    expect(screen.getByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(screen.getByText('This link can no longer be used.')).toBeInTheDocument();
    expect(screen.getByText('Or reply to the text message instead.')).toBeInTheDocument();
    expect(
      screen.getByText('A link works once. If you already sent your update, you will find it on the board.'),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for a new link, and says so once it has been sent', async () => {
    render(<LinkExpired token={LINK.expired} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send me a new link' }));
    expect(await screen.findByText('We have sent a new link.')).toBeInTheDocument();
    expect(seenBffRenews).toEqual([LINK.expired]);
  });

  it('says to wait, and sends nothing more, when the new-link budget is used up', async () => {
    render(<LinkExpired token={LINK.limited} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send me a new link' }));
    expect(await screen.findByText('Too many new links. Wait a few minutes, then try again.')).toBeInTheDocument();
    expect(screen.queryByText('We have sent a new link.')).toBeNull();
  });

  it('says a new link could not be sent when the request fails, and does not claim it was', async () => {
    server.use(http.post('/api/bff/links/:token/renew', () => HttpResponse.json({}, { status: 503 })));
    render(<LinkExpired token={LINK.expired} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send me a new link' }));
    expect(await screen.findByText('We could not send a new link. Try again.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('We have sent a new link.')).toBeNull());
  });
});
