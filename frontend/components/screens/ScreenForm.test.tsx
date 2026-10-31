import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ScreenClientError } from '@/lib/screens/client';
import { runAxe } from '@/test/a11y';
import { ScreenForm, type ConnectApi } from './ScreenForm';

// The ScreenPairing artboard, steps 2 and 3: the shift lead's page. Words are the prompt's.

const CONNECTED = { name: 'Control room', status: 'online' as const, connectedAt: '2026-10-23T13:12:00Z' };
const PREVIEW = { organisationName: 'Dorset Community Care', firstSeenAt: '2026-10-23T08:56:00Z', deviceClass: 'wall-display' as const };

function setup(connect: ConnectApi['connect'] = vi.fn(async () => CONNECTED), preview: ConnectApi['preview'] = vi.fn(async () => PREVIEW)) {
  const mocked = connect as ReturnType<typeof vi.fn>;
  const user = userEvent.setup();
  const view = render(<ScreenForm api={{ connect, preview }} />);
  return { user, connect: mocked, preview: preview as ReturnType<typeof vi.fn>, ...view };
}

/** Presses the form's button, waits for the confirm step (ScreenClaim) and presses its Connect screen. */
async function proceed(user: ReturnType<typeof userEvent.setup>) {
  await user.click(submit());
  await screen.findByRole('heading', { name: 'Check before you connect' });
  await user.click(submit());
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

  it('links to the list of screens already connected (W9I)', () => {
    setup();
    expect(screen.getByRole('link', { name: 'See the screens already connected' })).toHaveAttribute('href', '/lead/screens');
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
    await proceed(user);
    expect(connect).toHaveBeenCalledTimes(1);
    expect(connect).toHaveBeenCalledWith({ code: '482913', name: 'Control room', location: 'Ward 4 corridor' });
  });

  it('sends no place when none is typed', async () => {
    const { user, connect } = setup();
    await user.type(code(), '482913');
    await user.type(name(), 'Control room');
    await proceed(user);
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
    await proceed(user);
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
    await proceed(view.user);
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
    await proceed(user);
    expect(submit()).toBeDisabled();
    expect(submit()).toHaveAttribute('aria-busy', 'true');
    await proceed(user);
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
    await proceed(view.user);
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

  it('links the confirmation to the list of screens, where the screen can be disconnected (W9I)', async () => {
    const { user } = setup();
    await user.type(code(), '482 913');
    await user.type(name(), 'Control room');
    await proceed(user);
    expect(await screen.findByRole('link', { name: 'See all screens' })).toHaveAttribute('href', '/lead/screens');
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
    await proceed(view.user);
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
  it('has no axe violations in the empty form', async () => {
    const { container } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations with the errors showing', async () => {
    const { user, container } = setup();
    await proceed(user);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations with an alert above the form', async () => {
    const view = setup(vi.fn(async () => { throw failure('unavailable'); }));
    await view.user.type(code(), '482913');
    await view.user.type(name(), 'Control room');
    await proceed(view.user);
    await screen.findByRole('alert');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('has no axe violations when connected', async () => {
    const view = setup();
    await view.user.type(code(), '482913');
    await view.user.type(name(), 'Control room');
    await proceed(view.user);
    await waitFor(() => expect(screen.getByText('Screen connected')).toBeInTheDocument());
    expect(await runAxe(view.container)).toHaveNoViolations();
  });
});


describe('ScreenForm: the confirm step (ScreenClaim, TEN-072)', () => {
  async function toTheStep(options: { connect?: ConnectApi['connect']; preview?: ConnectApi['preview'] } = {}) {
    const view = setup(options.connect, options.preview);
    await view.user.type(code(), '482 913');
    await view.user.type(name(), 'Control room');
    await view.user.type(place(), 'Ward 4 corridor');
    await view.user.click(submit());
    return view;
  }

  it('asks the back end about the code first and connects nothing until the lead says so', async () => {
    const { preview, connect } = await toTheStep();
    expect(await screen.findByRole('heading', { level: 1, name: 'Check before you connect' })).toBeInTheDocument();
    expect(preview).toHaveBeenCalledTimes(1);
    expect(preview).toHaveBeenCalledWith('482913');
    expect(connect).not.toHaveBeenCalled();
  });

  it('says which organisation the screen will show, when it first asked and what kind of device it is', async () => {
    await toTheStep();
    await screen.findByText('Check before you connect');
    expect(screen.getByText('You are connecting a screen to Dorset Community Care. It will show our organisation’s capacity only. It never shows patient information.')).toBeInTheDocument();
    expect(screen.getByText('First seen 09:56 · Wall display')).toBeInTheDocument();
  });

  it('says "your organisation" when the organisation’s name could not be read', async () => {
    await toTheStep({ preview: vi.fn(async () => ({ ...PREVIEW, organisationName: null })) });
    await screen.findByText('Check before you connect');
    expect(screen.getByText(/^You are connecting a screen to your organisation\. /)).toBeInTheDocument();
  });

  it('shows an organisation name with markup as text', async () => {
    const view = await toTheStep({ preview: vi.fn(async () => ({ ...PREVIEW, organisationName: '<b>Trust</b>' })) });
    await screen.findByText('Check before you connect');
    expect(view.container.querySelector('b')).toBeNull();
    expect(screen.getByText(/<b>Trust<\/b>/)).toBeInTheDocument();
  });

  it('connects with what was typed when the lead presses Connect screen, and then shows the confirmation', async () => {
    const { user, connect } = await toTheStep();
    await screen.findByText('Check before you connect');
    await user.click(screen.getByRole('button', { name: 'Connect screen' }));
    expect(connect).toHaveBeenCalledWith({ code: '482913', name: 'Control room', location: 'Ward 4 corridor' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Screen connected' })).toBeInTheDocument();
  });

  it('goes back to the form, with what was typed, on Cancel, and connects nothing', async () => {
    const { user, connect } = await toTheStep();
    await screen.findByText('Check before you connect');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Add a wall screen' })).toBeInTheDocument();
    expect(code()).toHaveValue('482 913');
    expect(name()).toHaveValue('Control room');
    expect(connect).not.toHaveBeenCalled();
  });

  it('has the element ids of the step', async () => {
    const { container } = await toTheStep();
    await screen.findByText('Check before you connect');
    expect(container.querySelector('[data-el="SCREENS-CLAIM-CONFIRM-BTN"]')).toBe(screen.getByRole('button', { name: 'Connect screen' }));
    expect(container.querySelector('[data-el="SCREENS-CLAIM-CANCEL-BTN"]')).toBe(screen.getByRole('button', { name: 'Cancel' }));
  });

  it('moves the focus to the step’s heading', async () => {
    await toTheStep();
    expect(await screen.findByRole('heading', { level: 1, name: 'Check before you connect' })).toHaveFocus();
  });

  it('says the code is not valid, beside the code field, when the back end does not know it, and stays on the form', async () => {
    await toTheStep({ preview: vi.fn(async () => { throw failure('not-found'); }) });
    const message = await screen.findByText('That code is not valid or has expired. Check the screen for a new code.', { selector: 'p' });
    expect(code().getAttribute('aria-describedby')).toContain(message.id);
    expect(screen.queryByText('Check before you connect')).toBeNull();
  });

  it.each([
    ['throttled', 'Too many attempts. Wait a few minutes and try again.'],
    ['unavailable', 'We could not connect the screen. Try again.'],
  ] as const)('says %s as an alert above the form when the look at the code fails', async (kind, text) => {
    await toTheStep({ preview: vi.fn(async () => { throw failure(kind); }) });
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    expect(name()).toHaveValue('Control room');
  });

  it('is busy while it looks at the code, and a second press asks once', async () => {
    let finish: (value: typeof PREVIEW) => void = () => {};
    const preview = vi.fn(() => new Promise<typeof PREVIEW>((resolve) => (finish = resolve)));
    const { user } = await toTheStep({ preview });
    expect(submit()).toBeDisabled();
    await user.click(submit());
    expect(preview).toHaveBeenCalledTimes(1);
    finish(PREVIEW);
    await screen.findByText('Check before you connect');
  });

  it('keeps the step when connecting fails, and says so', async () => {
    const { user } = await toTheStep({ connect: vi.fn(async () => { throw failure('unavailable'); }) });
    await screen.findByText('Check before you connect');
    await user.click(screen.getByRole('button', { name: 'Connect screen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not connect the screen. Try again.');
  });

  it('has no axe violations on the step', async () => {
    const { container } = await toTheStep();
    await screen.findByText('Check before you connect');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
