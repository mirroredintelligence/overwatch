import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetStepSaves, seenStepSaves } from '@/test/msw/handlers/registration';
import { ReportingForm } from './ReportingForm';

// Registration step 4, how the service reports capacity (W26, artboard RegisterFlow2 panel 7). The
// API answer is saved after the reporting answers; a "Yes" reveals its four details.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

async function open() {
  const view = render(<ReportingForm registrationId={ID} />);
  await screen.findByRole('heading', { level: 1, name: 'How will you report capacity?' });
  return view;
}

async function fillValid() {
  await userEvent.click(screen.getByRole('button', { name: 'Referrals in the next 2 hrs' }));
  await userEvent.type(screen.getByLabelText('Lowest usual number'), '0');
  await userEvent.type(screen.getByLabelText('Highest usual number'), '8');
  await userEvent.click(screen.getByRole('button', { name: 'Every 2 hrs' }));
  await userEvent.click(screen.getByRole('button', { name: 'Text' }));
  await userEvent.type(screen.getByLabelText('Mobile number'), '07700 900456');
  await userEvent.type(screen.getByLabelText('Who holds this phone'), 'Sample Ward team');
  await userEvent.click(screen.getByRole('button', { name: 'No' }));
}

beforeEach(() => {
  push.mockClear();
  resetStepSaves();
});

describe('ReportingForm: the screen', () => {
  it('shows the counts, the usual range, the cadence and the channels, with the app note', async () => {
    await open();
    expect(screen.getByText('Step 4 of 5 · Capacity reporting')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'What do you count?' })).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Referrals in the next 2 hrs',
      'Beds free',
      'Slots left today',
      'Packages available',
      'Virtual beds free',
      'Other',
    ]);
    expect(screen.getByLabelText('Lowest usual number')).toBeInTheDocument();
    expect(screen.getByLabelText('Highest usual number')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'How often do you report?' })).toBeInTheDocument();
    expect(screen.getByText(/App notification needs the app on your home screen/)).toBeInTheDocument();
  });

  it('channel Email shows the email field and hides the mobile; Text shows the mobile', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Text' }));
    expect(screen.getByLabelText('Mobile number')).toHaveAccessibleDescription(
      'A ward or team phone is best. It stays with the post, not the person.',
    );
    expect(screen.queryByLabelText('Email address')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Email' }));
    expect(screen.getByLabelText('Email address')).toBeInTheDocument();
    expect(screen.queryByLabelText('Mobile number')).not.toBeInTheDocument();
  });

  it('shows the highest-below-lowest error on the highest field', async () => {
    await open();
    await userEvent.type(screen.getByLabelText('Lowest usual number'), '5');
    await userEvent.type(screen.getByLabelText('Highest usual number'), '2');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect((await screen.findAllByText('Highest usual number must be at least the lowest')).length).toBeGreaterThanOrEqual(1);
    expect(seenStepSaves).toHaveLength(0);
  });

  it('an API "Yes" with an http address shows the https error, and reveals the four details', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Yes' }));
    for (const label of ['API name', 'API address', 'Connection type', 'Type of data']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/Not used in the pilot. If you answer Yes/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('API address'), 'http://api.example.test');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect((await screen.findAllByText('Enter the API address, starting https://')).length).toBeGreaterThanOrEqual(1);
  });

  it('shows the "Other" count error, and the "Who holds this phone" error', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect((await screen.findAllByText('Choose what you count')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Enter who holds this phone').length).toBeGreaterThanOrEqual(1);
  });
});

describe('ReportingForm: saving', () => {
  it('a valid step 4 PUTs the coded values, then the API answer, and goes to the review', async () => {
    await open();
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/review`));
    const reporting = seenStepSaves.find((save) => save.step === 'reporting');
    expect(reporting).toMatchObject({
      csrf: 'csrf-sample-token',
      body: {
        measure: 'referrals-acceptable',
        usualRange: [0, 8],
        cadence: 'every-2-hrs',
        channel: 'text',
        holderName: 'Sample Ward team',
        contactMobile: '07700 900456',
      },
    });
    expect(seenStepSaves.find((save) => save.step === 'api')).toMatchObject({ body: { wanted: false } });
  });

  it('has no axe violations with errors shown', async () => {
    const { container } = await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findAllByText('Choose what you count');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
