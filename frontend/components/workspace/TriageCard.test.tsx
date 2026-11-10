import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NEEDS, URGENCIES } from '@/lib/advisor/codes';
import { runAxe } from '@/test/a11y';
import { TriageCard, type TriageCardProps } from './TriageCard';

// The triage card in the assistant thread (WS-TRI): the find form split into two steps. Controlled: every value and
// every change belongs to the parent.

function props(over: Partial<TriageCardProps> = {}): TriageCardProps {
  return {
    step: 'age',
    age: null,
    needs: [],
    urgency: null,
    postcodeSlot: <p>Postcode slot</p>,
    canNext: false,
    onAge: vi.fn(),
    onToggleNeed: vi.fn(),
    onUrgency: vi.fn(),
    onNext: vi.fn(),
    ...over,
  };
}

describe('TriageCard, age step', () => {
  it('WS-TRI-T01 shows the age step heading and four age buttons, none pressed, and no need or timeframe controls', () => {
    render(<TriageCard {...props()} />);
    expect(screen.getByRole('heading', { level: 3, name: 'Step 1 of 2 · Age and postcode' })).toBeInTheDocument();
    for (const label of ['0 to 15', '16 to 64', '65 to 79', '80+']) {
      expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'false');
    }
    expect(screen.queryByRole('group', { name: 'Patient need' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Required timeframe' })).toBeNull();
  });

  it('WS-TRI-T02 presses only the chosen age, which shows an aria-hidden tick, and a click calls onAge with its code', async () => {
    const onAge = vi.fn();
    const user = userEvent.setup();
    render(<TriageCard {...props({ age: '65-79', onAge })} />);
    const chosen = screen.getByRole('button', { name: '65 to 79' });
    expect(chosen).toHaveAttribute('aria-pressed', 'true');
    expect(chosen.querySelector('[aria-hidden="true"]')?.textContent).toBe('✓');
    expect(screen.getByRole('button', { name: '0 to 15' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: '16 to 64' }));
    expect(onAge).toHaveBeenCalledWith('16-64');
  });

  it('WS-TRI-T03 renders the postcode slot after the age fieldset and before the Next button', () => {
    render(<TriageCard {...props({ postcodeSlot: <p>Postcode slot</p> })} />);
    const ageGroup = screen.getByRole('group', { name: 'Patient age' });
    const slot = screen.getByText('Postcode slot');
    const next = screen.getByRole('button', { name: 'Next' });
    expect(ageGroup.compareDocumentPosition(slot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(slot.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('WS-TRI-T04 Next is aria-disabled with a visible hint while canNext is false, and a click does nothing', async () => {
    const onNext = vi.fn();
    const user = userEvent.setup();
    render(<TriageCard {...props({ canNext: false, onNext })} />);
    const next = screen.getByRole('button', { name: 'Next' });
    expect(next).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('Choose an age and a full postcode')).toBeVisible();
    await user.click(next);
    expect(onNext).not.toHaveBeenCalled();
  });

  it('WS-TRI-T04 Next has no aria-disabled, no hint, and a click calls onNext once when canNext is true', async () => {
    const onNext = vi.fn();
    const user = userEvent.setup();
    render(<TriageCard {...props({ canNext: true, age: '65-79', onNext })} />);
    const next = screen.getByRole('button', { name: 'Next' });
    expect(next).not.toHaveAttribute('aria-disabled', 'true');
    expect(screen.queryByText('Choose an age and a full postcode')).toBeNull();
    await user.click(next);
    expect(onNext).toHaveBeenCalledTimes(1);
  });
});

describe('TriageCard, need step', () => {
  it('WS-TRI-T05 shows one toggle per need, named by label, and a click calls onToggleNeed with its code; no age controls', async () => {
    const onToggleNeed = vi.fn();
    const user = userEvent.setup();
    render(<TriageCard {...props({ step: 'need', onToggleNeed })} />);
    expect(screen.getByRole('heading', { level: 3, name: 'Step 2 of 2 · Need and timeframe' })).toBeInTheDocument();
    const needs = within(screen.getByRole('group', { name: 'Patient need' })).getAllByRole('button');
    expect(needs).toHaveLength(NEEDS.length);
    expect(screen.queryByRole('group', { name: 'Patient age' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Frailty' }));
    expect(onToggleNeed).toHaveBeenCalledWith('frailty');
  });

  it('WS-TRI-T06 presses every selected need', () => {
    render(<TriageCard {...props({ step: 'need', needs: ['frailty', 'wound-care'] })} />);
    expect(screen.getByRole('button', { name: 'Frailty' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Wound care' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Palliative' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('WS-TRI-T07 shows the three timeframes, presses the chosen one, and a click calls onUrgency with its code', async () => {
    const onUrgency = vi.fn();
    const user = userEvent.setup();
    render(<TriageCard {...props({ step: 'need', urgency: 'today', onUrgency })} />);
    const timeframe = within(screen.getByRole('group', { name: 'Required timeframe' }));
    expect(timeframe.getAllByRole('button')).toHaveLength(URGENCIES.length);
    for (const item of URGENCIES) expect(timeframe.getByRole('button', { name: item.label })).toBeInTheDocument();
    expect(timeframe.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(timeframe.getByRole('button', { name: 'Planned' }));
    expect(onUrgency).toHaveBeenCalledWith('planned');
  });

  it('WS-TRI-T08 shows the results hint and has no Next button and no button matching find', () => {
    render(<TriageCard {...props({ step: 'need' })} />);
    expect(screen.getByText('Results appear when you choose a need and a timeframe.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull();
    expect(screen.queryByRole('button', { name: /find/i })).toBeNull();
  });
});

describe('TriageCard, both steps', () => {
  it('WS-TRI-T09 every button has type button and no element has a style attribute', () => {
    const { container, unmount } = render(<TriageCard {...props({ step: 'age', canNext: false })} />);
    const ageButtons = container.querySelectorAll('button');
    expect(ageButtons.length).toBeGreaterThan(0);
    for (const button of ageButtons) expect(button.getAttribute('type')).toBe('button');
    expect(container.querySelector('[style]')).toBeNull();
    unmount();

    const need = render(<TriageCard {...props({ step: 'need', needs: ['frailty'], urgency: 'today' })} />);
    const needButtons = need.container.querySelectorAll('button');
    expect(needButtons.length).toBeGreaterThan(0);
    for (const button of needButtons) expect(button.getAttribute('type')).toBe('button');
    expect(need.container.querySelector('[style]')).toBeNull();
  });

  it('WS-TRI-T10 the age step passes runAxe', async () => {
    const { container } = render(<TriageCard {...props({ step: 'age', age: '65-79', canNext: false })} />);
    expect(screen.getByRole('heading', { level: 3 })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('WS-TRI-T10 the need step passes runAxe', async () => {
    const { container } = render(<TriageCard {...props({ step: 'need', needs: ['frailty'], urgency: 'today' })} />);
    expect(screen.getByRole('heading', { level: 3 })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
