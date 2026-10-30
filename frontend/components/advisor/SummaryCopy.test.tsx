import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { SUMMARY_VIEW } from '@/test/msw/handlers/advisor';
import { SummaryCopy } from './SummaryCopy';

const EXPECTED =
  'Referrer: Ambulance crew\nAge band: 80+\nPostcode: DT4 8XX\nNeeds: Fall, Frailty\nUrgency: Within 2 hrs\n' +
  'Scores: NEWS2 2; Frailty scale 6 · Moderately frail\nDestination: UCR West\nBooked: Confirmed 14:19, reference 4821\n' +
  'Data age: Capacity 9 min old · criteria v3';

const writeText = vi.fn();

// user-event's setup() installs its own clipboard on navigator, so the mock goes in after it.
function useClipboard() {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
}

beforeEach(() => {
  writeText.mockReset();
});

describe('SummaryCopy (W15)', () => {
  it('shows the sample values as rows of the SystmOne summary', () => {
    render(<SummaryCopy summary={SUMMARY_VIEW} />);

    const section = screen.getByRole('region', { name: 'Summary for SystmOne' });
    expect(within(section).getByText('Read-only. Paste into the referral.')).toBeInTheDocument();
    for (const [label, value] of [
      ['Referrer', 'Ambulance crew'],
      ['Age band', '80+'],
      ['Postcode', 'DT4 8XX'],
      ['Needs', 'Fall, Frailty'],
      ['Urgency', 'Within 2 hrs'],
      ['Scores', 'NEWS2 2; Frailty scale 6 · Moderately frail'],
      ['Destination', 'UCR West'],
      ['Booked', 'Confirmed 14:19, reference 4821'],
      ['Data age', 'Capacity 9 min old · criteria v3'],
    ]) {
      expect(within(section).getByText(label)).toBeInTheDocument();
      expect(within(section).getByText(value)).toBeInTheDocument();
    }
  });

  it('"Copy summary" writes one row per line, and says so in a status region', async () => {
    writeText.mockResolvedValue(undefined);
    const user = userEvent.setup();
    useClipboard();
    render(<SummaryCopy summary={SUMMARY_VIEW} />);

    await user.click(byEl('ADV-FIN-COPY-BTN'));

    expect(writeText).toHaveBeenCalledWith(EXPECTED);
    expect(await screen.findByRole('status')).toHaveTextContent('Copied to clipboard');
  });

  it('when the clipboard refuses, the summary is selected and the user is told to press Ctrl+C', async () => {
    writeText.mockRejectedValue(new Error('refused'));
    const user = userEvent.setup();
    useClipboard();
    render(<SummaryCopy summary={SUMMARY_VIEW} />);

    await user.click(byEl('ADV-FIN-COPY-BTN'));

    expect(await screen.findByText('Press Ctrl+C to copy')).toBeInTheDocument();
    await waitFor(() => expect(window.getSelection()?.toString()).toContain('Referrer: Ambulance crew'));
  });

  it('"Done" is a link back to the outcome, and the summary has its anchor id', () => {
    const { container } = render(<SummaryCopy summary={SUMMARY_VIEW} />);

    expect(container.querySelector('#summary')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'Done' })).toHaveAttribute('href', '#outcome');
  });

  it('has no axe violations', async () => {
    render(<SummaryCopy summary={SUMMARY_VIEW} />);
    expect((await runAxe(document.body)).violations).toEqual([]);
  });
});
