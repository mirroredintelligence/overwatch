import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SERVICE_UCR_EAST } from '@/test/fixtures/lead';
import { PhonesList } from './PhonesList';

// The phones and the services they report for (W43). A phone is shown by its last digits only. A row opens to show
// the services on the phone and what can be done with each. The open row is a disclosure with aria-expanded.

function rowFor(ending: string): HTMLElement {
  return screen.getByRole('heading', { name: new RegExp(`···${ending}`) }).closest('li') as HTMLElement;
}

beforeEach(() => {
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

describe('PhonesList', () => {
  it('lists each phone by its last digits, in a row heading that names its role', async () => {
    render(<PhonesList />);
    await screen.findByRole('heading', { name: /···777/ });
    expect(within(rowFor('777')).getByText('Duty manager')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/07700\s?\d{6}/);
  });

  it('flags a phone that holds more than three services, in words', async () => {
    render(<PhonesList />);
    await screen.findByRole('heading', { name: /···777/ });
    expect(within(rowFor('777')).getByText(/Holds 4 services/)).toBeInTheDocument();
  });

  it('does not flag a phone with three services or fewer', async () => {
    render(<PhonesList />);
    await screen.findByRole('heading', { name: /···456/ });
    expect(within(rowFor('456')).queryByText(/Holds \d services/)).not.toBeInTheDocument();
  });

  it('says how many phones hold how many services, and how many have a flag', async () => {
    render(<PhonesList />);
    expect(await screen.findByText('2 phones hold 5 services. One has a flag.')).toBeInTheDocument();
  });

  it('opens a row to show its services, each with change number, move, and edit coverage', async () => {
    const user = userEvent.setup();
    render(<PhonesList />);
    const toggle = await screen.findByRole('button', { name: /···777/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '') as HTMLElement;
    expect(panel).toHaveAttribute('inert');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(panel).not.toHaveAttribute('inert');

    const service = within(panel).getByRole('heading', { name: 'UCR East' }).closest('section') as HTMLElement;
    expect(within(service).getByRole('link', { name: 'Change number' })).toHaveAttribute(
      'href',
      `/lead/reporters/number?service=${SERVICE_UCR_EAST}`,
    );
    expect(within(service).getByRole('link', { name: 'Move this service' })).toHaveAttribute(
      'href',
      `/lead/phones/move?service=${SERVICE_UCR_EAST}`,
    );
    expect(within(service).getByRole('link', { name: 'Edit the coverage area' })).toHaveAttribute(
      'href',
      `/lead/coverage/${SERVICE_UCR_EAST}`,
    );
  });

  it('opens a row from the keyboard', async () => {
    const user = userEvent.setup();
    render(<PhonesList />);
    const toggle = await screen.findByRole('button', { name: /···456/ });
    toggle.focus();
    await user.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('links Remove access to the removal page, pre-filled with the last digits of the phone', async () => {
    const user = userEvent.setup();
    render(<PhonesList />);
    const toggle = await screen.findByRole('button', { name: /···456/ });
    await user.click(toggle);
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '') as HTMLElement;
    expect(within(panel).getByRole('link', { name: 'Remove access' })).toHaveAttribute('href', '/lead/people/remove?person=456');
  });

  it('retires a service only after a confirmation that says what happens, and takes it off the list', async () => {
    let posted: string | null = null;
    server.use(
      http.post('/api/bff/lead/services/:id/retire', ({ params }) => {
        posted = String(params.id);
        return HttpResponse.json({ expiredRequests: 0 });
      }),
    );
    const user = userEvent.setup();
    render(<PhonesList />);
    const toggle = await screen.findByRole('button', { name: /777/ });
    await user.click(toggle);
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: 'Retire UCR East' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Retire UCR East?' });
    expect(posted).toBeNull();
    expect(within(dialog).getByText(/Its past reports and requests stay in the record/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Retire service' }));
    await waitFor(() => expect(posted).toBe(SERVICE_UCR_EAST));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(within(rowFor('777')).queryByRole('heading', { name: 'UCR East' })).not.toBeInTheDocument();
  });

  it('keeps the service when the lead chooses Keep service, and posts nothing', async () => {
    let called = false;
    server.use(http.post('/api/bff/lead/services/:id/retire', () => { called = true; return HttpResponse.json({}); }));
    const user = userEvent.setup();
    render(<PhonesList />);
    const toggle = await screen.findByRole('button', { name: /777/ });
    await user.click(toggle);
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: 'Retire UCR East' }));
    await user.click(await screen.findByRole('button', { name: 'Keep service' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(called).toBe(false);
  });

  it('says so, and keeps the service, when the retirement fails', async () => {
    server.use(http.post('/api/bff/lead/services/:id/retire', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    const user = userEvent.setup();
    render(<PhonesList />);
    const toggle = await screen.findByRole('button', { name: /777/ });
    await user.click(toggle);
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '') as HTMLElement;
    await user.click(within(panel).getByRole('button', { name: 'Retire UCR East' }));
    await user.click(await screen.findByRole('button', { name: 'Retire service' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not be retired. Try again.');
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('shows a loading state while the phones are read', async () => {
    render(<PhonesList />);
    expect(screen.getByText('Loading the phones.')).toBeInTheDocument();
    await screen.findByRole('heading', { name: /···777/ });
    expect(screen.queryByText('Loading the phones.')).not.toBeInTheDocument();
  });

  it('says when no phone holds a service, and shows no list', async () => {
    server.use(http.get('/api/bff/lead/phones', () => HttpResponse.json({ phones: [] })));
    render(<PhonesList />);
    expect(await screen.findByText('No phone holds a service yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Phones and the services they report for' })).not.toBeInTheDocument();
  });

  it('says the phones could not be loaded, and never shows an empty list for a failed read', async () => {
    server.use(http.get('/api/bff/lead/phones', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<PhonesList />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the phones.');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('links to moving a service and adding a service', async () => {
    render(<PhonesList />);
    await screen.findByRole('heading', { name: /···777/ });
    expect(screen.getByRole('link', { name: 'Move a service' })).toHaveAttribute('href', '/lead/phones/move');
    expect(screen.getByRole('link', { name: 'Add a service' })).toHaveAttribute('href', '/lead/services/new');
  });

  it('says that only the last digits of a number are shown', async () => {
    render(<PhonesList />);
    expect(await screen.findByText(/Only the last four digits of a number are shown\./)).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<PhonesList />);
    await screen.findByRole('heading', { name: /···777/ });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
