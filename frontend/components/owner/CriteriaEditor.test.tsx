import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { CriteriaValues } from '@/lib/criteria/types';
import { CriteriaEditor } from './CriteriaEditor';

const INITIAL: CriteriaValues = {
  accepts: ['fall-no-injury'],
  excludes: ['suspected-fracture', 'head-injury-anticoagulants'],
  ageMin: 18,
  ageMax: null,
  districts: ['DT1', 'DT2', 'DT3', 'DT4'],
};


// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CriteriaEditor', () => {
  it('shows the conflict and blocks Preview when a need is both accepted and not accepted', async () => {
    const user = userEvent.setup();
    const onPreview = vi.fn();
    const { container } = render(<CriteriaEditor initial={INITIAL} onPreview={onPreview} />);

    await user.click(within(screen.getByRole('group', { name: 'Needs you accept' })).getByRole('button', { name: 'Frailty' }));
    await user.click(within(screen.getByRole('group', { name: 'Needs you do not accept' })).getByRole('button', { name: 'Frailty' }));

    expect(await screen.findByText('A need cannot be both accepted and not accepted')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview the change' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Preview the change' }));
    expect(onPreview).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('clears the other exclusions when "No exclusions" is chosen', async () => {
    const user = userEvent.setup();
    render(<CriteriaEditor initial={INITIAL} onPreview={vi.fn()} />);
    const exclusions = within(screen.getByRole('group', { name: 'Needs you do not accept' }));
    expect(exclusions.getByRole('button', { name: 'Suspected fracture' })).toHaveAttribute('aria-pressed', 'true');
    expect(exclusions.getByRole('button', { name: 'Head injury on anticoagulants' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(exclusions.getByRole('button', { name: 'No exclusions' }));
    expect(exclusions.getByRole('button', { name: 'Suspected fracture' })).toHaveAttribute('aria-pressed', 'false');
    expect(exclusions.getByRole('button', { name: 'Head injury on anticoagulants' })).toHaveAttribute('aria-pressed', 'false');
    expect(exclusions.getByRole('button', { name: 'No exclusions' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('is headed "Change the criteria" and says which groups are required', () => {
    render(<CriteriaEditor initial={INITIAL} onPreview={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Change the criteria' })).toBeInTheDocument();
    expect(screen.getAllByText('(required)')).toHaveLength(3);
  });

  it('marks nothing as changed before anything is changed', () => {
    render(<CriteriaEditor initial={INITIAL} onPreview={vi.fn()} />);
    expect(screen.queryByText('Changed')).not.toBeInTheDocument();
    expect(screen.queryByText(/^was /)).not.toBeInTheDocument();
  });

  it('marks a changed age with the word "Changed" and what it was', async () => {
    const user = userEvent.setup();
    render(<CriteriaEditor initial={INITIAL} onPreview={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Decrease by one' }));
    await user.click(screen.getByRole('button', { name: 'Decrease by one' }));

    expect(screen.getByLabelText('Youngest age')).toHaveValue('16');
    expect(screen.getAllByText('Changed')).toHaveLength(1);
    expect(screen.getByText('was 18')).toBeInTheDocument();

    // Back to the saved value: the mark goes.
    await user.click(screen.getByRole('button', { name: 'Increase by one' }));
    await user.click(screen.getByRole('button', { name: 'Increase by one' }));
    expect(screen.queryByText('Changed')).not.toBeInTheDocument();
  });

  it('marks a changed list with "Changed" and the list it was', async () => {
    const user = userEvent.setup();
    render(<CriteriaEditor initial={INITIAL} onPreview={vi.fn()} />);
    await user.click(within(screen.getByRole('group', { name: 'Needs you accept' })).getByRole('button', { name: 'Frailty' }));

    expect(screen.getAllByText('Changed')).toHaveLength(1);
    expect(screen.getByText('was Fall, no injury')).toBeInTheDocument();
  });

  it('hands the values to onPreview from "Preview the change"', async () => {
    const user = userEvent.setup();
    const onPreview = vi.fn();
    render(<CriteriaEditor initial={INITIAL} onPreview={onPreview} />);
    await user.click(screen.getByRole('button', { name: 'Decrease by one' }));
    await user.click(screen.getByRole('button', { name: 'Preview the change' }));
    expect(onPreview).toHaveBeenCalledWith({ ...INITIAL, ageMin: 17 });
  });

  it('calls onCancel from Cancel', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<CriteriaEditor initial={INITIAL} onPreview={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
