import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ScreenClientError } from '@/lib/screens/client';
import { runAxe } from '@/test/a11y';
import { ScreenForm, type ConnectApi } from './ScreenForm';

// The ScreenPairing artboard, steps 2 and 3: the shift lead's page. Words are the prompt's.

const CONNECTED = { name: 'Control room', status: 'online' as const, connectedAt: '2026-10-23T13:12:00Z' };

function setup(connect: ConnectApi['connect'] = vi.fn(async () => CONNECTED)) {
  const mocked = connect as ReturnType<typeof vi.fn>;
  const user = userEvent.setup();
  const view = render(<ScreenForm api={{ connect }} />);
  return { user, connect: mocked, ...view };
}

const code = () => screen.getByLabelText(/Code shown on the screen/);
const name = () => screen.getByLabelText(/Screen name/);
const place = () => screen.getByLabelText(/Where it is/);
const submit = () => screen.getByRole('button', { name: 'Connect screen' });

function failure(kind: ScreenClientError['kind'], extra: Partial<ScreenClientError> = {}) {
  return Object.assign(new ScreenClientError(kind), extra);
}

describe('ScreenForm: the form', () => {
  it('shows the artboard’s heading, fields, note and buttons', () => {
    setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Add a wall screen' })).toBeInTheDocument();
    expect(code()).toBeInTheDocument();
    expect(screen.getByText('Required', { selector: '[data-el="LEAD-SCREEN-CODE-HINT"]' })).toBeInTheDocument();
    expect(name()).toBeInTheDocument();
    expect(place()).toBeInTheDocument();
    expect(screen.getByText('Optional')).toBeInTheDocument();
    expect(screen.getByText('This screen will show capacity only. It never shows patient information.')).toBeInTheDocument();
    expect(submit()).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/lead');
  });

  it('has the element ids', () => {
    const { container } = setup();
    for (const id of ['LEAD-SCREEN-CODE-FIELD', 'LEAD-SCREEN-NAME-FIELD', 'LEAD-SCREEN-LOCATION-FIELD', 'LEAD-SCREEN-CONNECT-BTN']) {
      expect(container.querySelector(`[data-el="${id}"]`), id).not.toBeNull();
    }
    expect(container.querySelector('[data-el="LEAD-SCREEN-CODE-FIELD"]')).toBe(code());
    expect(container.querySelector('[data-el="LEAD-SCREEN-CONNECT-BTN"]')).toBe(submit());
  });

  it('asks the phone for numbers and the browser for no memory of what is typed', () => {
    setup();
    expect(code()).toHaveAttribute('inputmode', 'numeric');
    expect(code()).toHaveAttribute('autocomplete', 'off');
    expect(name()).toHaveAttribute('autocomplete', 'off');
    expect(place()).toHaveAttribute('autocomplete', 'off');
  });

  it('sends the code without its space, the name and the place, as typed and trimmed', async () => {
    const { user, connect } = setup();
    await user.type(code(), '482 913');
    await user.type(name(), ' Control room ');
    await user.type(place(), ' Ward 4 corridor ');
    await user.click(submit());
    expect(connect).toHaveBeenCalledTimes(1);
    expect(connect).toHaveBeenCalledWith({ code: '482913', name: 'Control room', location: 'Ward 4 corridor' });
  });

  it('sends no place when none is typed', async () => {
    const { user, connect } = setup();
    await user.type(code(), '482913');
    await user.type(name(), 'Control room');
    await user.click(submit());
    expect(connect).toHaveBeenCalledWith({ code: '482913', name: 'Control room', location: null });
  });

  it('can be submitted with the keyboard', async () => {
    const { user, connect } = setup();
    await user.type(code(), '482913');
    await user.type(name(), 'Control room{Enter}');
    expect(connect).toHaveBeenCalledTimes(1);
  });

  it('offers no choice of board and sends no tenant, scope or network: a screen shows the organisation’s own board', async () => {
    const { user, connect, container } = setup();
    expect(container.querySelectorAll('select, input[type="radio"], input[type="hidden"]')).toHaveLength(0);
    await user.type(code(), '482913');
    await user.type(name(), 'Control room');
    await user.click(submit());
    expect(Object.keys(connect.mock.calls[0]![0] as object).sort()).toEqual(['code', 'location', 'name']);
  });
});

describe('ScreenForm: what is wrong with what was typed', () => {
  it('says each message beside its own field, links it to the field, and calls nothing', async () => {
    const { user, connect } = setup();
    await user.click(submit());
    expect(connect).not.toHaveBeenCalled();
    const codeError = screen.getByText('Enter the code shown on the screen', { selector: 'p' });
    const nameError = screen.getByText('Enter a name for the screen', { selector: 'p' });
    expect(code()).toHaveAttribute('aria-invalid', 'true');
    expect(code().getAttribute('aria-describedby')).toContain(codeError.id);
    expect(name()).toHaveAttribute('aria-invalid', 'true');
    expect(name().getAttribute('aria-describedby')).toContain(nameError.id);
    expect(place()).not.toHaveAttribute('aria-invalid', 'true');
  });

  it('puts the cursor on the first field that is wrong', async () => {
    const { user } = setup();
    await user.click(submit());
    expect(code()).toHaveFocus();
    await user.type(code(), '482913');
    await user.click(submit());
    expect(name()).toHaveFocus();
  });

  it('says the code has 6 numbers for five digits, letters and a long code', async () => {
    for (const typed of ['48291', '48291a', '4829133']) {
      const { user, connect, unmount } = setup();
      await user.type(code(), typed);
      await user.type(name(), 'Control room');
      await user.click(submit());
      expect(screen.getByText('The code has 6 numbers', { selector: 'p' })).toBeInTheDocument();
      expect(connect).not.toHaveBeenCalled();
      unmount();
    }
  });

  it('says a name of more than 60 characters is too long', async () => {
    const { user } = setup();
    await user.type(code(), '482913');
    await user.type(name(), 'a'.repeat(61));
    await user.click(submit());
    expect(screen.getByText('Use 60 characters or fewer.', { selector: 'p' })).toBeInTheDocument();
  });

  it('clears a message when the field is typed in again', async () => {
    const { user } = setup();
    await user.click(submit());
    await user.type(code(), '4');
    expect(screen.queryByText('Enter the code shown on the screen')).toBeNull();
    expect(code()).not.toHaveAttribute('aria-invalid', 'true');
  });
});

describe('ScreenForm: what the back end says', () => {
  async function submitGood(connect: ConnectApi['connect']) {
    const view = setup(connect);
    await view.user.type(code(), '482913');
    await view.user.type(name(), 'Control room');
    await view.user.click(submit());
    return view;
  }

  it('says the code is not valid or has expired, beside the code field, for a 404', async () => {
    await submitGood(vi.fn(async () => { throw failure('not-found'); }));
    const message = await screen.findByText('That code is not valid or has expired. Check the screen for a new code.', { selector: 'p' });
    expect(code().getAttribute('aria-describedby')).toContain(message.id);
    expect(code()).toHaveAttribute('aria-invalid', 'true');
    expect(code()).toHaveFocus();
    expect(code()).toHaveValue('482913');
  });

  it('says the words of the BFF beside the field it names for an invalid name', async () => {
    await submitGood(vi.fn(async () => { throw failure('invalid', { field: 'name', detail: 'Check the screen name and where it is. Do not include patient information.' }); }));
    const message = await screen.findByText('Check the screen name and where it is. Do not include patient information.', { selector: 'p' });
    expect(name().getAttribute('aria-describedby')).toContain(message.id);
  });

  it.each([
    ['throttled', 'Too many attempts. Wait a few minutes and try again.'],
    ['unavailable', 'We could not connect the screen. Try again.'],
  ] as const)('says %s as an alert above the form, and keeps what was typed', async (kind, text) => {
    await submitGood(vi.fn(async () => { throw failure(kind); }));
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    expect(name()).toHaveValue('Control room');
    expect(submit()).not.toBeDisabled();
  });

  it('says the session has ended, with a way to sign in again, when the lead is no longer signed in', async () => {
    await submitGood(vi.fn(async () => { throw failure('unauthorised'); }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Your session has ended. Sign in again.');
    expect(within(alert).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Flead%2Fscreens%2Fnew');
  });

  it('is busy while it waits, and a second press does not send a second connect', async () => {
    let finish: (value: typeof CONNECTED) => void = () => {};
    const connect = vi.fn(() => new Promise<typeof CONNECTED>((resolve) => (finish = resolve)));
    const { user } = setup(connect);
    await user.type(code(), '482913');
    await user.type(name(), 'Control room');
    await user.click(submit());
    expect(submit()).toBeDisabled();
    expect(submit()).toHaveAttribute('aria-busy', 'true');
    await user.click(submit());
    expect(connect).toHaveBeenCalledTimes(1);
    finish(CONNECTED);
    await screen.findByText('Screen connected');
  });
});

describe('ScreenForm: connected', () => {
  async function connected() {
    const view = setup(vi.fn(async () => ({ name: 'Control room', status: 'online' as const, connectedAt: '2026-10-23T13:12:00Z' })));
    await view.user.type(code(), '482913');
    await view.user.type(name(), 'Control room');
    await view.user.click(submit());
    await screen.findByText('Screen connected');
    return view;
  }

  it('shows the artboard’s confirmation with the time in London', async () => {
    await connected();
    expect(screen.getByRole('heading', { level: 1, name: 'Screen connected' })).toBeInTheDocument();
    expect(screen.getByText('Control room is now showing the live board.')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Online, updated 14:12')).toBeInTheDocument();
    expect(screen.getByText('Shows')).toBeInTheDocument();
    expect(screen.getByText('Capacity only. No patient information.')).toBeInTheDocument();
    expect(screen.getByText('If it goes offline')).toBeInTheDocument();
    expect(screen.getByText('The board shows Last known and says so')).toBeInTheDocument();
  });

  it('says the status with a word, not a colour alone', async () => {
    await connected();
    expect(screen.getByText(/^Online, updated/)).toBeInTheDocument();
  });

  it('moves the focus to the confirmation, so a screen reader hears it', async () => {
    await connected();
    expect(screen.getByRole('heading', { level: 1, name: 'Screen connected' })).toHaveFocus();
  });

  it('offers Add another screen, which shows an empty form again, and Done, which goes to the lead page', async () => {
    const { user } = await connected();
    expect(screen.getByRole('link', { name: 'Done' })).toHaveAttribute('href', '/lead');
    await user.click(screen.getByRole('button', { name: 'Add another screen' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Add a wall screen' })).toBeInTheDocument();
    expect(code()).toHaveValue('');
    expect(name()).toHaveValue('');
    expect(code()).toHaveFocus();
  });

  it('shows a name with markup as text', async () => {
    const view = setup(vi.fn(async () => ({ name: '<b>x</b>', status: 'online' as const, connectedAt: '2026-10-23T13:12:00Z' })));
    await view.user.type(code(), '482913');
    await view.user.type(name(), 'x');
    await view.user.click(submit());
    expect(await screen.findByText('<b>x</b> is now showing the live board.')).toBeInTheDocument();
    expect(view.container.querySelector('b')).toBeNull();
  });

  it('has the element ids for the two buttons', async () => {
    const { container } = await connected();
    expect(container.querySelector('[data-el="LEAD-SCREEN-ADD-ANOTHER-BTN"]')).not.toBeNull();
    expect(container.querySelector('[data-el="LEAD-SCREEN-DONE-BTN"]')).not.toBeNull();
  });
});

describe('ScreenForm: accessibility', () => {
  it('has no axe violations in the form, with errors, with an alert, and when connected', async () => {
    const { user, container, unmount } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
    await user.click(submit());
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();

    const alerting = setup(vi.fn(async () => { throw failure('unavailable'); }));
    await alerting.user.type(code(), '482913');
    await alerting.user.type(name(), 'Control room');
    await alerting.user.click(submit());
    await screen.findByRole('alert');
    expect(await runAxe(alerting.container)).toHaveNoViolations();
    alerting.unmount();

    const done = setup();
    await done.user.type(code(), '482913');
    await done.user.type(name(), 'Control room');
    await done.user.click(submit());
    await waitFor(() => expect(screen.getByText('Screen connected')).toBeInTheDocument());
    expect(await runAxe(done.container)).toHaveNoViolations();
  });
});
