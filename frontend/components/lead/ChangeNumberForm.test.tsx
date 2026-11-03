import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { SERVICE_REABLEMENT } from '@/test/fixtures/lead';
import { ChangeNumberForm } from './ChangeNumberForm';

// The change-reporter-number state (W18, pilot; INV-03): the Detail state of the one reporters page with the
// "Change their number" row open. The list of invitations stays on the left, the open reporter's set-up is
// beside it, and the row sits among the actions. A reporter whose set-up is complete has no actions, and a
// service with no invitation has no detail: those get the same form on a card.

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/lead/reporters/number',
}));

const STUCK_SERVICE = 's-ucr-west';

beforeEach(() => {
  resetLeadPosts();
  router.push.mockClear();
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

/** The row, open: its field, read once the invitations have loaded. */
async function openField(): Promise<HTMLElement> {
  return screen.findByLabelText('New mobile number');
}

async function sendNumber(user: ReturnType<typeof userEvent.setup>, number: string, cover: string) {
  await user.type(await openField(), number);
  await user.click(screen.getByRole('button', { name: cover }));
  await user.click(screen.getByRole('button', { name: 'Send a new invitation' }));
}

describe('ChangeNumberForm', () => {
  describe('the detail state with the row open', () => {
    it('has the page heading Reporters, the list of invitations and the open reporter beside it', async () => {
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      expect(screen.getByRole('heading', { level: 1, name: 'Reporters' })).toBeInTheDocument();
      expect(await screen.findByRole('region', { name: 'Set-up progress' })).toBeInTheDocument();
      const detail = await screen.findByRole('region', { name: 'UCR West set-up' });
      expect(within(detail).getByRole('heading', { level: 2, name: 'UCR West' })).toBeInTheDocument();
    });

    it('marks the open reporter in the list', async () => {
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      const list = await screen.findByRole('region', { name: 'Set-up progress' });
      const rows = await within(list).findAllByRole('button', { name: /UCR West/ });
      expect(rows[0]).toHaveAttribute('aria-current', 'true');
    });

    it('opens the change-number row among the actions, with its hint and the field', async () => {
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      const actions = await screen.findByRole('group', { name: 'What you can do' });
      const toggle = within(actions).getByRole('button', { name: 'Change their number' });
      expect(toggle).toHaveAttribute('aria-expanded', 'true');
      expect(within(actions).getByText('The new number gets a fresh code. The old one stops working.')).toBeInTheDocument();
      expect(within(actions).getByLabelText('New mobile number')).toBeVisible();
    });

    it('closes and opens the row from its heading', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      const toggle = await screen.findByRole('button', { name: 'Change their number' });
      await user.click(toggle);
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByLabelText('New mobile number')).not.toBeVisible();
      await user.click(toggle);
      expect(toggle).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByLabelText('New mobile number')).toBeVisible();
    });

    it('opens another reporter from the list, and goes back to the list from Back to the list', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      const list = await screen.findByRole('region', { name: 'Set-up progress' });
      await user.click(await within(list).findByRole('button', { name: /Reablement/ }));
      expect(router.push).toHaveBeenLastCalledWith('/lead/reporters?invitation=inv-2');
      await user.click(screen.getByRole('button', { name: 'Back to the list' }));
      expect(router.push).toHaveBeenLastCalledWith('/lead/reporters');
    });

    it('shows the number the service reports to now, by its last four digits', async () => {
      server.use(
        http.get('/api/bff/lead/reporters', () =>
          HttpResponse.json({ reporters: [{ serviceId: STUCK_SERVICE, name: 'UCR West', numberEnding: '4821', until: null }] }),
        ),
      );
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      expect(await screen.findByText('Current number ends 4821')).toBeInTheDocument();
      expect(document.body.textContent ?? '').not.toMatch(/07700\s?9\d{5}/);
    });

    it('says the old number stops working as soon as it is saved', async () => {
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      expect(
        await screen.findByText('The old number stops working as soon as you save. Both numbers are logged.'),
      ).toBeInTheDocument();
    });

    it('posts "this-week" for a cover chosen as This week, then says the new number ends 0456', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      await sendNumber(user, '07700 900456', 'This week');
      expect(await screen.findByRole('status')).toHaveTextContent('New number ending 0456 saved');
      expect(seenLeadPosts).toHaveLength(1);
      expect(seenLeadPosts[0]).toMatchObject({
        path: '/api/bff/lead/reporters/number',
        csrf: 'test-csrf-token',
        body: { serviceId: STUCK_SERVICE, newNumber: '07700 900456', until: 'this-week' },
      });
      expect(seenLeadPosts[0].idempotencyKey).toBeTruthy();
    });

    it('never shows the full new number after saving, and clears the field', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      const field = await openField();
      await sendNumber(user, '07700 900456', 'This week');
      await screen.findByText('New number ending 0456 saved');
      expect(document.body.textContent ?? '').not.toMatch(/07700\s?900456/);
      await waitFor(() => expect(field).toHaveValue(''));
    });

    it('offers a test text only after the number is saved', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      expect(await screen.findByRole('button', { name: 'Send a test text' })).toBeDisabled();
      await sendNumber(user, '07700 900456', 'Today');
      await screen.findByText('New number ending 0456 saved');
      await user.click(screen.getByRole('button', { name: 'Send a test text' }));
      expect(await screen.findByRole('status')).toHaveTextContent('Test text sent.');
      expect(seenLeadPosts[1].path).toBe(`/api/bff/lead/services/${STUCK_SERVICE}/test-prompt`);
    });

    it('refuses a number that is not a UK mobile', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      await user.type(await openField(), '0123');
      await user.click(screen.getByRole('button', { name: 'Send a new invitation' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('Enter a UK mobile number, like 07700 900456');
      expect(seenLeadPosts).toHaveLength(0);
    });

    it('asks for how long when none is chosen', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      await user.type(await openField(), '07700 900456');
      await user.click(screen.getByRole('button', { name: 'Send a new invitation' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('Choose the service and how long the cover lasts.');
      expect(seenLeadPosts).toHaveLength(0);
    });

    it('says so when the number could not be changed', async () => {
      server.use(http.post('/api/bff/lead/reporters/number', () => HttpResponse.json({ code: 'x' }, { status: 500 })));
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      await sendNumber(user, '07700 900456', 'Today');
      expect(await screen.findByRole('alert')).toHaveTextContent('The number could not be changed. Try again.');
    });

    it('has no axe violations', async () => {
      const { container } = render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      await screen.findByRole('button', { name: 'Send a new invitation' });
      expect(await runAxe(container)).toHaveNoViolations();
    });
  });

  describe('a reporter with no actions, or no invitation', () => {
    it('shows the form on a card for a service whose set-up is complete, with the number it reports to', async () => {
      render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
      expect(await screen.findByRole('heading', { level: 2, name: 'Change their number' })).toBeInTheDocument();
      expect(await screen.findByText('Current number ends 0377')).toBeInTheDocument();
      expect(screen.getByRole('combobox', { name: 'Service' })).toHaveValue(SERVICE_REABLEMENT);
    });

    it('posts from the card the same way', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
      await sendNumber(user, '07700 900456', 'Until I change it');
      expect(await screen.findByRole('status')).toHaveTextContent('New number ending 0456 saved');
      expect(seenLeadPosts[0]).toMatchObject({ body: { serviceId: SERVICE_REABLEMENT, until: 'until-changed' } });
    });

    it('asks which service when none is in the address', async () => {
      const user = userEvent.setup();
      render(<ChangeNumberForm />);
      const choose = await screen.findByRole('combobox', { name: 'Service' });
      expect(choose).toHaveValue('');
      await user.selectOptions(choose, await screen.findByRole('option', { name: 'Reablement' }));
      expect(await screen.findByText('Current number ends 0377')).toBeInTheDocument();
    });

    it('keeps the form when the invitations cannot be loaded, and says so in the list', async () => {
      server.use(http.get('/api/bff/lead/invitations', () => HttpResponse.json({ code: 'x' }, { status: 500 })));
      render(<ChangeNumberForm serviceId={STUCK_SERVICE} />);
      expect(await screen.findByText('We could not load set-up progress')).toBeInTheDocument();
      expect(await screen.findByLabelText('New mobile number')).toBeInTheDocument();
    });

    it('has no axe violations', async () => {
      const { container } = render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
      await screen.findByRole('button', { name: 'Send a new invitation' });
      expect(await runAxe(container)).toHaveNoViolations();
    });
  });
});
