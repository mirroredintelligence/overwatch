import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { CASE_ETAG, resetSeenAdvisorRequests, seenCasePuts } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { NeedsForm } from './NeedsForm';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const OPENED = '2026-10-30T10:00:00.000Z';

beforeEach(() => {
  push.mockReset();
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

async function renderForm() {
  const result = render(<NeedsForm caseId="4821" openedAt={OPENED} />);
  await screen.findByRole('group', { name: 'Who is calling?' });
  return result;
}

async function fillEverything(user: ReturnType<typeof userEvent.setup>) {
  await user.click(byEl('ADV-NEEDS-REFERRER-AMBULANCE'));
  await user.click(byEl('ADV-NEEDS-AGE-80PLUS'));
  await user.type(screen.getByLabelText('Where is the patient? Postcode'), 'DT4 8XX');
  await user.click(byEl('ADV-NEEDS-NEED-FALL-NO-INJURY'));
  await user.click(byEl('ADV-NEEDS-NEED-FRAILTY'));
  await user.click(byEl('ADV-NEEDS-URGENCY-WITHIN-2-HRS'));
}

describe('NeedsForm (W11)', () => {
  it('shows the loading line until the case is read, and no form to edit before then', () => {
    render(<NeedsForm caseId="4821" openedAt={OPENED} />);

    expect(screen.getByText('Loading the case.')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Who is calling?' })).toBeNull();
  });

  it('says so when the case cannot be read, and offers no save', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<NeedsForm caseId="4821" openedAt={OPENED} />);

    expect(await screen.findByText('This case could not be loaded.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'See options' })).toBeNull();
  });

  it('choosing 80+ sets aria-pressed on it and clears the other age chips', async () => {
    const user = userEvent.setup();
    await renderForm();

    await user.click(byEl('ADV-NEEDS-AGE-80PLUS'));

    expect(byEl('ADV-NEEDS-AGE-80PLUS')).toHaveAttribute('aria-pressed', 'true');
    for (const other of ['ADV-NEEDS-AGE-0-15', 'ADV-NEEDS-AGE-16-64', 'ADV-NEEDS-AGE-65-79']) {
      expect(byEl(other)).toHaveAttribute('aria-pressed', 'false');
    }
  });

  it('needs are multi-select, and "More needs" reveals the four extra chips', async () => {
    const user = userEvent.setup();
    await renderForm();

    await user.click(byEl('ADV-NEEDS-NEED-FALL-NO-INJURY'));
    await user.click(byEl('ADV-NEEDS-NEED-FRAILTY'));
    expect(byEl('ADV-NEEDS-NEED-FALL-NO-INJURY')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('ADV-NEEDS-NEED-FRAILTY')).toHaveAttribute('aria-pressed', 'true');
    expect(document.querySelector('[data-el="ADV-NEEDS-NEED-DEMENTIA"]')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'More needs' }));
    for (const id of [
      'ADV-NEEDS-NEED-DEMENTIA',
      'ADV-NEEDS-NEED-SUSPECTED-FRACTURE',
      'ADV-NEEDS-NEED-HEAD-INJURY-ANTICOAGULANTS',
      'ADV-NEEDS-NEED-INFECTION-ISOLATION',
    ]) {
      expect(byEl(id)).toBeInTheDocument();
    }
  });

  it('"See options" stays disabled until referrer, age, postcode, a need and urgency are all set', async () => {
    const user = userEvent.setup();
    await renderForm();
    const continueButton = byEl('ADV-NEEDS-CONTINUE-BTN');
    expect(continueButton).toBeDisabled();

    await user.click(byEl('ADV-NEEDS-REFERRER-AMBULANCE'));
    await user.click(byEl('ADV-NEEDS-AGE-80PLUS'));
    await user.type(screen.getByLabelText('Where is the patient? Postcode'), 'DT4 8XX');
    await user.click(byEl('ADV-NEEDS-NEED-FRAILTY'));
    expect(continueButton).toBeDisabled();

    await user.click(byEl('ADV-NEEDS-URGENCY-TODAY'));
    expect(continueButton).toBeEnabled();
  });

  it('normalises the postcode on blur, and an invalid one shows the error linked to the field', async () => {
    const user = userEvent.setup();
    await renderForm();
    const postcode = screen.getByLabelText('Where is the patient? Postcode');

    await user.type(postcode, 'dt48xx');
    await user.tab();
    expect(postcode).toHaveValue('DT4 8XX');
    expect(screen.queryByText('Enter a full postcode, for example DT4 8XX')).toBeNull();

    await user.clear(postcode);
    await user.type(postcode, 'DT4 8X');
    await user.tab();
    const error = screen.getByText('Enter a full postcode, for example DT4 8XX');
    expect(postcode).toHaveAttribute('aria-invalid', 'true');
    expect(postcode.getAttribute('aria-describedby')).toContain(error.id);
  });

  it('submit sends PUT with If-Match from the read ETag and the coded body, then goes to the options', async () => {
    const user = userEvent.setup();
    await renderForm();
    await fillEverything(user);

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/advisor/case/4821/options'));
    expect(seenCasePuts).toHaveLength(1);
    expect(seenCasePuts[0].ifMatch).toBe(CASE_ETAG);
    expect(seenCasePuts[0].body).toEqual({
      referrerType: 'ambulance-crew',
      ageBand: '80+',
      postcode: 'DT4 8XX',
      needs: ['fall-no-injury', 'frailty'],
      urgency: 'within-2-hrs',
      scores: [],
    });
  });

  it('never puts the postcode in the URL of the save', async () => {
    const user = userEvent.setup();
    await renderForm();
    await fillEverything(user);

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    expect(seenCasePuts[0].url).not.toMatch(/DT4|8XX/);
  });

  it('a 412 shows the conflict message and does not navigate', async () => {
    server.use(
      http.put('/api/bff/cases/:ref', () => HttpResponse.json({ code: 'conflict' }, { status: 412 })),
    );
    const user = userEvent.setup();
    await renderForm();
    await fillEverything(user);

    await user.click(byEl('ADV-NEEDS-CONTINUE-BTN'));

    expect(await screen.findByText('This case changed in another window. Reload to see the latest.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('Tab reaches the chips in reading order and Space toggles the focused chip', async () => {
    const user = userEvent.setup();
    await renderForm();
    byEl('ADV-NEEDS-REFERRER-AMBULANCE').focus();

    const order: string[] = [];
    for (let step = 0; step < 6; step += 1) {
      order.push(document.activeElement?.getAttribute('data-el') ?? '');
      await user.tab();
    }
    expect(order).toEqual([
      'ADV-NEEDS-REFERRER-AMBULANCE',
      'ADV-NEEDS-REFERRER-CARE-HOME',
      'ADV-NEEDS-REFERRER-GP',
      'ADV-NEEDS-REFERRER-NHS-111',
      'ADV-NEEDS-REFERRER-OTHER',
      'ADV-NEEDS-AGE-0-15',
    ]);

    byEl('ADV-NEEDS-REFERRER-GP').focus();
    await user.keyboard(' ');
    expect(byEl('ADV-NEEDS-REFERRER-GP')).toHaveAttribute('aria-pressed', 'true');
  });

  it('has no axe violations with the form loaded', async () => {
    const { container } = await renderForm();
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('shows the note about names and postcodes being cleared', async () => {
    await renderForm();
    expect(
      screen.getByText('No patient name is stored. Postcode and needs are cleared after the call record closes.'),
    ).toBeInTheDocument();
  });
});
