import { render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import type { Score } from '@/lib/advisor/scores';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { PATHWAYS_BACKEND_CALLS, PATHWAYS_RESULTS } from '@/test/msw/handlers/advisor';
import { ScorePickers } from './ScorePickers';

beforeEach(() => {
  resetCsrfCache();
  PATHWAYS_BACKEND_CALLS.length = 0;
});

// The parent holds the scores, as NeedsForm does: a change is shown once the parent has kept it.
function Harness({ initial, onChange }: { initial: Score[]; onChange: (scores: Score[]) => void }) {
  const [scores, setScores] = useState<Score[]>(initial);
  return (
    <ScorePickers
      value={scores}
      onChange={(next) => {
        setScores(next);
        onChange(next);
      }}
    />
  );
}

function setup(initial: Score[] = []) {
  const onChange = vi.fn();
  const view = render(<Harness initial={initial} onChange={onChange} />);
  return { onChange, ...view };
}

const lastScores = (fn: ReturnType<typeof vi.fn>): Score[] => fn.mock.calls.at(-1)?.[0] as Score[];

describe('ScorePickers (W12)', () => {
  it('row "Score from the referrer (optional)" offers the five methods and "Not given"', () => {
    setup();

    expect(screen.getByRole('group', { name: 'Score from the referrer (optional)' })).toBeInTheDocument();
    for (const id of ['PATHWAYS', 'AMBULANCE', 'MANCHESTER', 'NEWS2', 'CFS', 'NONE']) {
      expect(byEl(`ADV-SCORE-${id}-CHIP`)).toHaveAttribute('aria-pressed', 'false');
    }
    expect(screen.queryByRole('spinbutton')).toBeNull();
  });

  it('choosing NEWS2 shows its input; "21" shows the error and records nothing; "2" is recorded', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();

    await user.click(byEl('ADV-SCORE-NEWS2-CHIP'));
    const input = screen.getByLabelText('NEWS2 score (0 to 20)');
    await user.type(input, '21');
    expect(screen.getByText('Enter a whole number from 0 to 20')).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    // Typing "2" first records 2; "21" then clears it, so nothing is recorded at the end.
    expect(lastScores(onChange).some((score) => score.method === 'news2')).toBe(false);

    await user.clear(input);
    await user.type(input, '2');
    expect(screen.queryByText('Enter a whole number from 0 to 20')).toBeNull();
    expect(lastScores(onChange)).toEqual([{ method: 'news2', value: 2 }]);
  });

  it('choosing Frailty scale 6 shows "6 · Moderately frail" and records 6', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();

    await user.click(byEl('ADV-SCORE-CFS-CHIP'));
    await user.click(byEl('ADV-SCORE-CFS-6'));

    expect(screen.getByText('6 · Moderately frail')).toBeInTheDocument();
    expect(lastScores(onChange)).toEqual([{ method: 'cfs', value: 6 }]);
  });

  it('"Not given" clears every chosen method and hides the pickers', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(byEl('ADV-SCORE-NEWS2-CHIP'));
    await user.type(screen.getByLabelText('NEWS2 score (0 to 20)'), '3');
    await user.click(byEl('ADV-SCORE-CFS-CHIP'));
    await user.click(byEl('ADV-SCORE-CFS-4'));

    await user.click(byEl('ADV-SCORE-NONE-CHIP'));

    expect(byEl('ADV-SCORE-NEWS2-CHIP')).toHaveAttribute('aria-pressed', 'false');
    expect(byEl('ADV-SCORE-CFS-CHIP')).toHaveAttribute('aria-pressed', 'false');
    expect(byEl('ADV-SCORE-NONE-CHIP')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByLabelText('NEWS2 score (0 to 20)')).toBeNull();
    expect(screen.queryByRole('group', { name: 'Clinical Frailty Scale (1 to 9)' })).toBeNull();
    expect(lastScores(onChange)).toEqual([]);
  });

  it('Pathways search calls the BFF once after the debounce and lists results', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(byEl('ADV-SCORE-PATHWAYS-CHIP'));

    await user.type(screen.getByRole('searchbox', { name: 'Search Dx code or description' }), 'fa');

    await waitFor(() => expect(pathwaysOptionCount()).toBe(PATHWAYS_RESULTS.length), { timeout: 8000 });
    expect(PATHWAYS_BACKEND_CALLS).toHaveLength(1);
    expect(PATHWAYS_BACKEND_CALLS[0]).toBe('fa');
    expect(screen.getByRole('button', { name: `${PATHWAYS_RESULTS[0].code} · ${PATHWAYS_RESULTS[0].display}` })).toBeInTheDocument();
  });

  it('typed text alone records nothing; choosing a result records its code', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(byEl('ADV-SCORE-PATHWAYS-CHIP'));
    await user.type(screen.getByRole('searchbox', { name: 'Search Dx code or description' }), 'Dx101');
    expect(onChange.mock.calls.every((call) => (call[0] as Score[]).length === 0)).toBe(true);

    await waitFor(() => expect(pathwaysOptionCount()).toBeGreaterThan(0), { timeout: 8000 });
    await user.click(screen.getByRole('button', { name: `${PATHWAYS_RESULTS[0].code} · ${PATHWAYS_RESULTS[0].display}` }));

    expect(lastScores(onChange)).toEqual([{ method: 'pathways-dx', value: PATHWAYS_RESULTS[0].code }]);
    expect(screen.getByText('Choose from the list. Codes cannot be typed freely.')).toBeInTheDocument();
  });

  it('Ambulance category 2 records value 2 and says it is recorded as the crew gave it', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(byEl('ADV-SCORE-AMBULANCE-CHIP'));

    await user.click(screen.getByRole('button', { name: /Category 2/ }));

    expect(lastScores(onChange)).toEqual([{ method: 'ambulance-category', value: 2 }]);
    expect(screen.getByText('Recorded as the crew gave it.')).toBeInTheDocument();
    expect(screen.getByText('Used by 999')).toBeInTheDocument();
  });

  it('Manchester triage offers the five words and records the chosen one', async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(byEl('ADV-SCORE-MANCHESTER-CHIP'));

    for (const label of ['Immediate', 'Very urgent', 'Urgent', 'Standard', 'Non-urgent']) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeInTheDocument();
    }
    await user.click(screen.getByRole('button', { name: /Very urgent/ }));

    expect(lastScores(onChange)).toEqual([{ method: 'manchester', value: 'very-urgent' }]);
    expect(
      screen.getByText('Only for referrers who have already triaged in an emergency department.'),
    ).toBeInTheDocument();
  });

  it('Frailty chips are reachable with Tab and toggle with Space', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(byEl('ADV-SCORE-CFS-CHIP'));

    byEl('ADV-SCORE-CFS-1').focus();
    await user.keyboard(' ');
    expect(byEl('ADV-SCORE-CFS-1')).toHaveAttribute('aria-pressed', 'true');
    await user.tab();
    expect(document.activeElement).toBe(byEl('ADV-SCORE-CFS-2'));
  });

  it('shows the footnote, and has no axe violations with every picker open', async () => {
    const user = userEvent.setup();
    const { container } = setup();
    for (const chip of ['PATHWAYS', 'AMBULANCE', 'MANCHESTER', 'NEWS2', 'CFS']) {
      await user.click(byEl(`ADV-SCORE-${chip}-CHIP`));
    }
    expect(
      screen.getByText('Scores are recorded as the referrer gave them. The tool does not calculate or check them.'),
    ).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

/** How many Pathways results are on screen now. */
function pathwaysOptionCount(): number {
  return document.querySelectorAll('[data-el="ADV-SCORE-PATHWAYS-OPTION"]').length;
}
