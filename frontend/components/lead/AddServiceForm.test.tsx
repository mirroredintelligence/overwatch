import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { AddServiceForm } from './AddServiceForm';

// Filling the whole form types into about fifteen fields, so these tests get more than the default 5 s.
const FORM_TIMEOUT_MS = 20_000;

// The page's address is a small store the mock of next/navigation reads and writes: the form keeps its step in
// `?step=`, so Back and a reload work (the history is what the browser's Back walks).
const nav = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const state = { search: '', history: [] as string[] };
  const emit = () => listeners.forEach((l) => l());
  return {
    state,
    listeners,
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    set(search: string) {
      state.search = search;
      state.history = [];
    },
    push(url: string) {
      state.history.push(state.search);
      state.search = url.includes('?') ? url.slice(url.indexOf('?') + 1) : '';
      emit();
    },
    back() {
      state.search = state.history.pop() ?? '';
      emit();
    },
  };
});

vi.mock('next/navigation', async () => {
  const { useSyncExternalStore } = await import('react');
  const search = () => nav.state.search;
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(nav.subscribe, search, search)),
    useRouter: () => ({ push: nav.push, replace: nav.push, back: nav.back }),
    usePathname: () => '/lead/services/new',
  };
});

// The shift lead's add-a-service form (W18, pilot; LDR-03 and LDR-04: four steps and the added state on one form
// state). The form posts JSON to the BFF, which sends the FHIR Parameters to the back end's $setup. Each step is
// checked on "Next"; the problems are shown in a summary at the top of the step and inline. Step 4 checks the
// whole form again, then "Add the service" posts it.

beforeEach(() => {
  resetLeadPosts();
  nav.set('');
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

async function fillStep1(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Service name'), 'Reablement');
  await user.click(screen.getByRole('button', { name: 'Reablement' }));
  await user.type(screen.getByLabelText('Unit label'), 'referrals in the next 2 hrs');
  await user.click(screen.getByRole('button', { name: 'Referrals in the next 2 hrs' }));
  await user.type(screen.getByLabelText('Established'), '4');
  await user.type(screen.getByLabelText('Usual low'), '0');
  await user.type(screen.getByLabelText('Usual high'), '8');
  await user.type(screen.getByLabelText('From'), '08:00');
  await user.type(screen.getByLabelText('To'), '20:00');
}

async function fillStep2(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Every 2 hrs' }));
  await user.type(screen.getByLabelText('Mobile number for text'), '07700 900456');
  await user.type(screen.getByLabelText('Who holds this phone'), 'Duty manager');
}

async function fillStep3(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Frailty' }));
  await user.type(screen.getByLabelText('Youngest age'), '18');
  await user.type(screen.getByLabelText('Postcode districts'), 'DT4');
  await user.type(screen.getByLabelText('Review criteria by'), '2031-01-31');
}

async function toStep2(user: ReturnType<typeof userEvent.setup>) {
  await fillStep1(user);
  await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
  await screen.findByRole('heading', { name: 'Who reports, and how' });
}

async function toStep3(user: ReturnType<typeof userEvent.setup>) {
  await toStep2(user);
  await fillStep2(user);
  await user.click(screen.getByRole('button', { name: 'Next: who it takes' }));
  await screen.findByRole('heading', { name: 'Who it takes' });
}

async function toCheck(user: ReturnType<typeof userEvent.setup>) {
  await toStep3(user);
  await fillStep3(user);
  await user.click(screen.getByRole('button', { name: 'Next: check' }));
  await screen.findByRole('heading', { name: 'Check, then add it' });
}

describe('AddServiceForm', { timeout: FORM_TIMEOUT_MS }, () => {
  it('opens on step 1, "The service", with the step bar saying so', () => {
    render(<AddServiceForm />);
    expect(screen.getByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    const bar = screen.getByRole('navigation', { name: 'Setup steps' });
    expect(bar.querySelector('[aria-current="step"]')).toHaveTextContent('The service');
  });

  it('does not ask who owns the criteria: the back end has no such field yet', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep3(user);
    expect(screen.queryByText('Who owns these criteria')).toBeNull();
  });

  it('refuses a blank step 1: a summary with a link to each problem, focus on it, and it stays on step 1', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
    const summary = await screen.findByRole('alert');
    expect(summary).toHaveTextContent(/There are \d+ problems/);
    expect(summary).toHaveFocus();
    expect(screen.getByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    expect(nav.state.search).toBe('');
    const link = within(summary).getByRole('link', { name: 'Enter the service name' });
    await user.click(link);
    expect(screen.getByLabelText('Service name')).toHaveFocus();
  });

  it('only checks the step it is on: step 1 never asks for the mobile number', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
    const summary = await screen.findByRole('alert');
    expect(within(summary).queryByRole('link', { name: /mobile number/ })).toBeNull();
  });

  it('refuses a highest usual number below the lowest', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await user.type(screen.getByLabelText('Usual low'), '5');
    await user.type(screen.getByLabelText('Usual high'), '4');
    await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
    expect(
      (await screen.findAllByText('Highest usual number must be at least the lowest')).length,
    ).toBeGreaterThan(0);
  });

  it('goes to step 2 when step 1 is right, and puts the step in the address', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep2(user);
    expect(nav.state.search).toBe('step=2');
    const bar = screen.getByRole('navigation', { name: 'Setup steps' });
    expect(bar.querySelector('[aria-current="step"]')).toHaveTextContent('Who reports');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('accepts 07700 900456 and refuses 0123 with the mobile message, on step 2', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep2(user);
    await user.click(screen.getByRole('button', { name: 'Every 2 hrs' }));
    await user.type(screen.getByLabelText('Who holds this phone'), 'Duty manager');
    await user.type(screen.getByLabelText('Mobile number for text'), '0123');
    await user.click(screen.getByRole('button', { name: 'Next: who it takes' }));
    expect(await screen.findAllByText('Enter a UK mobile number, like 07700 900456')).not.toHaveLength(0);
    expect(screen.getByRole('heading', { level: 1, name: 'Who reports, and how' })).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Mobile number for text'));
    await user.type(screen.getByLabelText('Mobile number for text'), '07700 900456');
    await user.click(screen.getByRole('button', { name: 'Next: who it takes' }));
    expect(await screen.findByRole('heading', { name: 'Who it takes' })).toBeInTheDocument();
    expect(screen.queryAllByText('Enter a UK mobile number, like 07700 900456')).toHaveLength(0);
  });

  it('keeps what was typed when Back is pressed, and when the browser goes back', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep2(user);
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    expect(screen.getByLabelText('Service name')).toHaveValue('Reablement');
    await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
    await screen.findByRole('heading', { name: 'Who reports, and how' });
    act(() => nav.back());
    expect(await screen.findByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    expect(screen.getByLabelText('Service name')).toHaveValue('Reablement');
  });

  it('opens on the step in the address after a reload', () => {
    nav.set('step=2');
    render(<AddServiceForm />);
    expect(screen.getByRole('heading', { level: 1, name: 'Who reports, and how' })).toBeInTheDocument();
  });

  it('pins what has been entered on the left from step 2, with the phone as its last four digits only', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    expect(screen.queryByRole('region', { name: 'What you have entered' })).toBeNull();
    await toStep2(user);
    const pin = screen.getByRole('region', { name: 'What you have entered' });
    expect(pin).toHaveTextContent('Reablement');
    await fillStep2(user);
    await user.click(screen.getByRole('button', { name: 'Next: who it takes' }));
    await screen.findByRole('heading', { name: 'Who it takes' });
    expect(pin).toHaveTextContent('Duty manager, by text');
    expect(pin).toHaveTextContent('Phone ending 0456');
    expect(pin).not.toHaveTextContent('07700');
  });

  it('goes back to a step from "Change" in the pinned summary', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep3(user);
    const pin = screen.getByRole('region', { name: 'What you have entered' });
    await user.click(within(pin).getByRole('button', { name: 'Change who reports' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Who reports, and how' })).toBeInTheDocument();
    expect(screen.getByLabelText('Who holds this phone')).toHaveValue('Duty manager');
  });

  it('stores nothing in the browser while it is filled in', async () => {
    const user = userEvent.setup();
    const set = vi.spyOn(Storage.prototype, 'setItem');
    render(<AddServiceForm />);
    await toStep2(user);
    expect(set).not.toHaveBeenCalled();
    set.mockRestore();
  });

  it('has four steps in the bar, the last of them "Check"', () => {
    render(<AddServiceForm />);
    const bar = screen.getByRole('navigation', { name: 'Setup steps' });
    expect(within(bar).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('The service'),
      expect.stringContaining('Who reports'),
      expect.stringContaining('Who it takes'),
      expect.stringContaining('Check'),
    ]);
  });

  it('goes from step 3 to the check with "Next: check" once step 3 is right, and puts step 4 in the address', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    expect(nav.state.search).toBe('step=4');
    const bar = screen.getByRole('navigation', { name: 'Setup steps' });
    expect(bar.querySelector('[aria-current="step"]')).toHaveTextContent('Check');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('refuses a blank step 3 on "Next: check" with a summary at the top of step 3', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep3(user);
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Next: check' }));
    const summary = await screen.findByRole('alert');
    expect(summary).toHaveTextContent(/There are \d+ problems/);
    expect(summary).toHaveFocus();
    expect(screen.getByRole('heading', { level: 1, name: 'Who it takes' })).toBeInTheDocument();
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('shows what was entered on the check, three cards, and the warning', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    expect(screen.getByRole('group', { name: 'The service' })).toHaveTextContent('Reablement');
    expect(screen.getByRole('group', { name: 'Who reports' })).toHaveTextContent('Phone ending 0456');
    expect(screen.getByRole('group', { name: 'Who it takes' })).toHaveTextContent('Age 18+');
    expect(screen.getByText(/Advisors will see these criteria as soon as you add the service/)).toBeInTheDocument();
  });

  it('adds "Who it takes" to the pinned summary on the check, and does not pin it on step 3', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep3(user);
    await fillStep3(user);
    const pin = screen.getByRole('region', { name: 'What you have entered' });
    expect(pin).not.toHaveTextContent('Who it takes');
    await user.click(screen.getByRole('button', { name: 'Next: check' }));
    await screen.findByRole('heading', { name: 'Check, then add it' });
    expect(pin).toHaveTextContent('Who it takes');
    expect(pin).toHaveTextContent('Frailty');
    expect(pin).toHaveTextContent('review by 31 Jan 2031');
  });

  it('closes the pinned summary once the service is added', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    await screen.findByRole('heading', { level: 1, name: 'Reablement is added' });
    expect(screen.queryByRole('region', { name: 'What you have entered' })).toBeNull();
  }, FORM_TIMEOUT_MS);

  it('goes back to the step from "Change" on a card of the check, keeping what was typed', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    const card = screen.getByRole('group', { name: 'Who it takes' });
    await user.click(within(card).getByRole('button', { name: 'Change who it takes' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Who it takes' })).toBeInTheDocument();
    expect(screen.getByLabelText('Postcode districts')).toHaveValue('DT4');
    expect(nav.state.search).toBe('step=3');
  });

  it('goes back from the check with Back', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Who it takes' })).toBeInTheDocument();
  });

  it('posts the form as JSON with the CSRF token and an idempotency key from the check, then says the service is added', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    const heading = await screen.findByRole('heading', { level: 1, name: 'Reablement is added' });
    expect(heading).toHaveFocus();
    expect(seenLeadPosts).toHaveLength(1);
    const [post] = seenLeadPosts;
    expect(post.csrf).toBe('test-csrf-token');
    expect(post.idempotencyKey).toBeTruthy();
    expect(post.body).toMatchObject({
      name: 'Reablement',
      category: 'reablement',
      measure: 'referrals-acceptable',
      cadence: 'every-2-hrs',
      channel: 'text',
      mobile: '07700 900456',
      ageMin: 18,
      districts: ['DT4'],
      accepts: ['frailty'],
    });
  }, FORM_TIMEOUT_MS);

  it('offers the invite link for the new service once it is added, and no step bar', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    await screen.findByRole('heading', { level: 1, name: 'Reablement is added' });
    expect(screen.getByRole('link', { name: 'Invite the reporter' })).toHaveAttribute('href', '/lead/reporters/invite?service=s-new-1');
    expect(screen.queryByRole('navigation', { name: 'Setup steps' })).toBeNull();
  }, FORM_TIMEOUT_MS);

  it('starts again, blank and on step 1, from "Add another service"', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    await screen.findByRole('heading', { level: 1, name: 'Reablement is added' });
    await user.click(screen.getByRole('button', { name: 'Add another service' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    expect(screen.getByLabelText('Service name')).toHaveValue('');
    expect(nav.state.search).toBe('step=1');
    const bar = screen.getByRole('navigation', { name: 'Setup steps' });
    expect(bar.querySelector('[aria-current="step"]')).toHaveTextContent('The service');
    expect(seenLeadPosts).toHaveLength(1);
  }, FORM_TIMEOUT_MS);

  it('takes the lead back to the step with the first problem when it is added from the check with an earlier step wrong', async () => {
    const user = userEvent.setup();
    nav.set('step=4');
    render(<AddServiceForm />);
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'The service' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent(/There are \d+ problems/);
    expect(nav.state.search).toBe('step=1');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has no axe violations with the errors shown', async () => {
    const user = userEvent.setup();
    const { container } = render(<AddServiceForm />);
    await user.click(screen.getByRole('button', { name: 'Next: who reports' }));
    await screen.findByRole('alert');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says the pilot is for text or email only', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toStep3(user);
    expect(screen.getByText('Services with neither text nor email are outside the MVP.')).toBeInTheDocument();
  });

  it('keeps the same idempotency key when a failed save is sent again', async () => {
    server.use(
      http.post('/api/bff/lead/services', ({ request }) => {
        seenLeadPosts.push({
          path: '/api/bff/lead/services',
          csrf: request.headers.get('x-csrf-token'),
          idempotencyKey: request.headers.get('idempotency-key'),
          body: undefined,
        });
        return HttpResponse.json({ code: 'exception', message: 'x' }, { status: 503 });
      }),
    );
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await toCheck(user);
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not be saved.');
    expect(screen.getByRole('heading', { level: 1, name: 'Check, then add it' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add the service' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(2));
    expect(seenLeadPosts[1].idempotencyKey).toBe(seenLeadPosts[0].idempotencyKey);
  }, FORM_TIMEOUT_MS);
});
