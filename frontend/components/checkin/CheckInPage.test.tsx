import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { server } from '@/test/msw/server';
import { CheckInPage } from './CheckInPage';

// The page a service's printed QR code opens (DEC-1346): a number, a texted code, then on or off shift.

const TOKEN = 'AbCdEfGhIjKlMnOpQrStUvW';
const BASE = `/api/bff/checkin/${TOKEN}`;
const MOBILE = '07700 900111';

let writes: { path: string; csrf: string | null; body: unknown }[] = [];

function serve(options: { read?: () => Response; code?: () => Response; confirm?: () => Response } = {}) {
  const record = async (path: string, request: Request) => {
    writes.push({ path, csrf: request.headers.get('x-csrf-token'), body: await request.json() });
  };
  server.use(
    http.get(BASE, () => options.read?.() ?? HttpResponse.json({ service: 'UCR West', csrfToken: 'page-csrf' })),
    http.post(`${BASE}/code`, async ({ request }) => {
      await record('code', request);
      return options.code?.() ?? HttpResponse.json({ state: 'sent' }, { status: 202 });
    }),
    http.post(`${BASE}/confirm`, async ({ request }) => {
      await record('confirm', request);
      return options.confirm?.() ?? HttpResponse.json({ state: 'on-shift', service: 'UCR West', until: '18:00' });
    }),
  );
}

beforeEach(() => {
  writes = [];
});

async function toCodeStep(user: ReturnType<typeof userEvent.setup>) {
  render(<CheckInPage token={TOKEN} />);
  await user.type(await screen.findByLabelText(/Your mobile number/), MOBILE);
  await user.click(byEl('CHECKIN-SEND-BTN'));
  await screen.findByText(/a code is on its way/);
}

describe('CheckInPage', () => {
  it('names the service and asks for the mobile number, and writes nothing on opening', async () => {
    serve();
    render(<CheckInPage token={TOKEN} />);

    expect(await screen.findByRole('heading', { name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Your mobile number/)).toBeInTheDocument();
    expect(writes).toHaveLength(0);
  });

  it('refuses a number that is not a UK mobile and asks for nothing', async () => {
    serve();
    const user = userEvent.setup();
    render(<CheckInPage token={TOKEN} />);
    await user.type(await screen.findByLabelText(/Your mobile number/), '12345');

    await user.click(byEl('CHECKIN-SEND-BTN'));

    expect(await screen.findByText(/Enter a UK mobile number/)).toBeInTheDocument();
    expect(writes).toHaveLength(0);
  });

  it('asks for a code with the number and the page CSRF token, then says one is on its way without saying who is registered', async () => {
    serve();
    const user = userEvent.setup();

    await toCodeStep(user);

    expect(writes).toEqual([{ path: 'code', csrf: 'page-csrf', body: { mobile: MOBILE } }]);
    expect(screen.getByText(/If that number is registered for this service/)).toBeInTheDocument();
    expect(byEl('CHECKIN-ON-BTN')).toBeDisabled();
  });

  it('starts the shift for the hours chosen and says when it ends', async () => {
    serve();
    const user = userEvent.setup();
    await toCodeStep(user);

    await user.selectOptions(screen.getByLabelText('How long is your shift?'), '10');
    await user.type(screen.getByLabelText('6-digit code'), '123456');
    await user.click(byEl('CHECKIN-ON-BTN'));

    expect(await screen.findByText('You are on shift for UCR West until 18:00.')).toBeInTheDocument();
    expect(writes.at(-1)).toEqual({ path: 'confirm', csrf: 'page-csrf', body: { mobile: MOBILE, code: '123456', action: 'on', hours: 10 } });
  });

  it('finishes the shift with no hours', async () => {
    serve({ confirm: () => HttpResponse.json({ state: 'off-shift' }) });
    const user = userEvent.setup();
    await toCodeStep(user);

    await user.type(screen.getByLabelText('6-digit code'), '123456');
    await user.click(byEl('CHECKIN-OFF-BTN'));

    expect(await screen.findByText('You are off shift for UCR West.')).toBeInTheDocument();
    expect(writes.at(-1)?.body).toEqual({ mobile: MOBILE, code: '123456', action: 'off' });
  });

  it('says a wrong code did not work, clears it, and lets the person try again', async () => {
    serve({ confirm: () => HttpResponse.json({ state: 'code-wrong' }, { status: 403 }) });
    const user = userEvent.setup();
    await toCodeStep(user);

    await user.type(screen.getByLabelText('6-digit code'), '000000');
    await user.click(byEl('CHECKIN-ON-BTN'));

    expect(await screen.findByRole('alert')).toHaveTextContent('That code did not work');
    expect(screen.getByLabelText('6-digit code')).toHaveValue('');
  });

  it('says to wait when there have been too many tries', async () => {
    serve({ code: () => HttpResponse.json({ state: 'rate-limited' }, { status: 429 }) });
    const user = userEvent.setup();
    render(<CheckInPage token={TOKEN} />);
    await user.type(await screen.findByLabelText(/Your mobile number/), MOBILE);

    await user.click(byEl('CHECKIN-SEND-BTN'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many tries');
  });

  it('goes back to the number to use a different one', async () => {
    serve();
    const user = userEvent.setup();
    await toCodeStep(user);

    await user.click(screen.getByRole('button', { name: 'Use a different number' }));

    expect(await screen.findByLabelText(/Your mobile number/)).toBeInTheDocument();
  });

  it('shows the closed-link page for a code that is gone, and the unavailable page when it cannot be read', async () => {
    serve({ read: () => HttpResponse.json({ state: 'gone' }, { status: 410 }) });
    const { unmount } = render(<CheckInPage token={TOKEN} />);
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'UCR West' })).not.toBeInTheDocument());
    await screen.findByRole('heading');
    expect(screen.queryByLabelText(/Your mobile number/)).not.toBeInTheDocument();
    unmount();

    serve({ read: () => HttpResponse.json({ state: 'unavailable' }, { status: 503 }) });
    render(<CheckInPage token={TOKEN} />);
    expect(await screen.findByText('This link did not open')).toBeInTheDocument();
  });

  it('has no accessibility violations on either step', async () => {
    serve();
    const user = userEvent.setup();
    const { container } = render(<CheckInPage token={TOKEN} />);
    await screen.findByLabelText(/Your mobile number/);
    expect(await runAxe(container)).toHaveNoViolations();
    await user.type(screen.getByLabelText(/Your mobile number/), MOBILE);
    await user.click(byEl('CHECKIN-SEND-BTN'));
    await screen.findByLabelText('6-digit code');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
