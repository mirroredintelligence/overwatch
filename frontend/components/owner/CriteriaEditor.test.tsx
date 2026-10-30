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

describe('CriteriaEditor', () => {
  it('shows the conflict and blocks Preview when a need is both accepted and not accepted', async () => {
    const user = userEvent.setup();
    const onPreview = vi.fn();
    const { container } = render(<CriteriaEditor initial={INITIAL} onPreview={onPreview} />);

    await user.click(within(screen.getByRole('group', { name: 'Needs you accept' })).getByRole('button', { name: 'Frailty' }));
    await user.click(within(screen.getByRole('group', { name: 'Needs you do not accept' })).getByRole('button', { name: 'Frailty' }));

    expect(await screen.findByText('A need cannot be both accepted and not accepted')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Preview' }));
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
});
