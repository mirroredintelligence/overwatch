import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { addressState, resetAddressRequests, seenAddressRequests, seenStepSaves, resetStepSaves } from '@/test/msw/handlers/registration';
import { LocationForm } from './LocationForm';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

// These flows type through a whole form in one test: the suite's default five seconds is too little on a loaded machine.
vi.setConfig({ testTimeout: 20_000 });

// Registration step 2, where the service is (W24, artboards RegisterFlow1 panel 4 and RegisterMobile
// panel 3). A fixed site takes an address from a postcode lookup; a visiting service skips the site.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

async function open() {
  const view = render(<LocationForm registrationId={ID} />);
  await screen.findByRole('heading', { level: 1, name: 'Where is the service?' });
  return view;
}

async function choose(name: string) {
  await userEvent.click(screen.getByRole('button', { name }));
}

async function findAddress(postcode: string) {
  await userEvent.type(screen.getByLabelText('Postcode'), postcode);
  await userEvent.click(screen.getByRole('button', { name: 'Find address' }));
}

async function fillFixedSite() {
  await choose('Yes, a building or ward');
  await findAddress('dt4 8xx');
  await userEvent.click(await screen.findByRole('button', { name: /Sample House/ }));
  await userEvent.type(screen.getByLabelText('Site name'), 'Sample Ward');
  await choose('Ward');
  await choose('Mon');
  await userEvent.type(screen.getByLabelText('Opens'), '08:00');
  await userEvent.type(screen.getByLabelText('Closes'), '20:00');
}

beforeEach(() => {
  push.mockClear();
  resetStepSaves();
  resetAddressRequests();
  addressState.lookup = { status: 200, body: [
    { id: 'addr-1', label: 'Sample House, Dorchester, DT4 8XX' },
    { id: 'addr-2', label: 'Sample Flat, Dorchester, DT4 8XX' },
    { id: 'addr-3', label: 'Sample Lodge, Dorchester, DT4 8XX' },
  ] };
});

describe('LocationForm: the fixed-site question', () => {
  it('shows the question, its options and the hint, and the step label', async () => {
    await open();
    expect(screen.getByText('Step 2 of 5 · Location')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Do you have a fixed site?' })).toBeInTheDocument();
    expect(screen.getByText(/Choose No for services that visit patients/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes, a building or ward' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No, we visit patients' })).toBeInTheDocument();
  });

  it('choosing "No, we visit patients" hides the site fields, and Continue PUTs only the answer and goes to step 3', async () => {
    await open();
    await choose('Yes, a building or ward');
    expect(screen.getByLabelText('Postcode')).toBeInTheDocument();
    await choose('No, we visit patients');
    expect(screen.queryByLabelText('Postcode')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Site name')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/service`));
    expect(seenStepSaves[0]).toMatchObject({ step: 'location', body: { fixedSite: false } });
  });
});

describe('LocationForm: the address lookup', () => {
  it('Find address asks the BFF for the normalised postcode and lists the addresses to choose from', async () => {
    await open();
    await choose('Yes, a building or ward');
    await findAddress('dt4 8xx');
    expect(await screen.findByRole('group', { name: 'Choose the address' })).toBeInTheDocument();
    expect(seenAddressRequests).toEqual(['DT4 8XX']);
    const group = screen.getByRole('group', { name: 'Choose the address' });
    expect(within(group).getAllByRole('button')).toHaveLength(3);
  });

  it('an empty lookup shows the not-found error on the postcode field', async () => {
    addressState.lookup = { status: 200, body: [] };
    await open();
    await choose('Yes, a building or ward');
    await findAddress('DT4 8XX');
    expect(await screen.findByText('We could not find that postcode. Check it and try again.')).toBeInTheDocument();
    expect(screen.getByLabelText('Postcode')).toHaveAttribute('aria-invalid', 'true');
  });

  it('choosing an address shows the position note and keeps the address', async () => {
    await open();
    await choose('Yes, a building or ward');
    await findAddress('DT4 8XX');
    await userEvent.click(await screen.findByRole('button', { name: /Sample Flat/ }));
    expect(screen.getByText('Position found from the address. You do not need to enter coordinates.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sample Flat/ })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('LocationForm: opening hours', () => {
  it('"24 hours" clears the chosen days and hides the time fields', async () => {
    await open();
    await choose('Yes, a building or ward');
    await choose('Mon');
    await choose('Tue');
    expect(screen.getByRole('button', { name: 'Mon' })).toHaveAttribute('aria-pressed', 'true');
    await choose('24 hours');
    expect(screen.getByRole('button', { name: 'Mon' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Tue' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByLabelText('Opens')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Closes')).not.toBeInTheDocument();
  });

  it('a closing time before the opening time shows its error on the closing time', async () => {
    await open();
    await choose('Yes, a building or ward');
    await choose('Mon');
    await userEvent.type(screen.getByLabelText('Opens'), '20:00');
    await userEvent.type(screen.getByLabelText('Closes'), '08:00');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect((await screen.findAllByText('The closing time must be after the opening time')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText('Closes')).toHaveAttribute('aria-invalid', 'true');
    expect(seenStepSaves).toHaveLength(0);
  });
});

describe('LocationForm: validation and saving', () => {
  it('Continue with nothing chosen shows the summary, focused, with its links', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    const heading = await screen.findByRole('heading', { name: 'There is a problem' });
    const region = heading.closest('[role="alert"]') as HTMLElement;
    expect(region).toHaveFocus();
    expect(within(region).getByRole('link', { name: 'Choose whether you have a fixed site' })).toBeInTheDocument();
    expect(seenStepSaves).toHaveLength(0);
  });

  it('a valid fixed site PUTs the expected body and goes to step 3', async () => {
    await open();
    await fillFixedSite();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/service`));
    expect(seenStepSaves[0]).toMatchObject({
      step: 'location',
      csrf: 'csrf-sample-token',
      body: {
        fixedSite: true,
        postcode: 'DT4 8XX',
        addressId: 'addr-1',
        address: 'Sample House, Dorchester, DT4 8XX',
        siteName: 'Sample Ward',
        siteType: 'ward',
        hours: { days: [0], allDay: false, opens: '08:00', closes: '20:00' },
      },
    });
  }, 30_000);

  it('has no axe violations with errors shown', async () => {
    const { container } = await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'There is a problem' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
