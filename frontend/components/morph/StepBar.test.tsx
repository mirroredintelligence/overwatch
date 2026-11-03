import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StepBar } from './StepBar';

// The numbered pills of a guided flow (boards/lead/AddService.dc.html). The current step is aria-current="step";
// a step already visited can be gone back to; a step not yet reached is shown but cannot be pressed.

const STEPS = [{ label: 'The service' }, { label: 'Who reports' }, { label: 'Who it takes' }, { label: 'Check' }];

describe('StepBar', () => {
  it('is a labelled nav with an ordered list of the steps', () => {
    render(<StepBar label="Setup steps" steps={STEPS} current={0} />);
    const nav = screen.getByRole('navigation', { name: 'Setup steps' });
    expect(nav.querySelectorAll('li')).toHaveLength(4);
    expect(nav.querySelector('ol')).not.toBeNull();
  });

  it('marks only the current step with aria-current="step"', () => {
    render(<StepBar label="Setup steps" steps={STEPS} current={1} />);
    const current = document.querySelectorAll('[aria-current="step"]');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('Who reports');
  });

  it('shows the step number, and a tick for steps that are done', () => {
    render(<StepBar label="Setup steps" steps={STEPS} current={2} />);
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('✓');
    expect(items[1]).toHaveTextContent('✓');
    expect(items[2]).toHaveTextContent('3');
    expect(items[3]).toHaveTextContent('4');
  });

  it('says in words which steps are done, current or not yet reached', () => {
    render(<StepBar label="Setup steps" steps={STEPS} current={1} onSelect={() => undefined} />);
    expect(screen.getByRole('button', { name: 'Step 1, done: The service' })).toBeInTheDocument();
    expect(screen.getByText('Step 2, current: Who reports')).toBeInTheDocument();
    expect(screen.getByText('Step 3, not reached yet: Who it takes')).toBeInTheDocument();
  });

  it('lets a visited step be chosen, through onSelect with its index', () => {
    const onSelect = vi.fn();
    render(<StepBar label="Setup steps" steps={STEPS} current={2} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button', { name: /Step 1, done/ }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  it('does not make the current step or a step not yet reached pressable', () => {
    render(<StepBar label="Setup steps" steps={STEPS} current={1} onSelect={() => undefined} />);
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /Who it takes/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Who reports/ })).toBeNull();
  });

  it('keeps a step reached earlier pressable after going back, with `reached`', () => {
    const onSelect = vi.fn();
    render(<StepBar label="Setup steps" steps={STEPS} current={0} reached={2} onSelect={onSelect} />);
    expect(screen.getByRole('button', { name: /Step 2, visited/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Step 3, visited/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Step 4/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Step 3, visited/ }));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it('draws a visited step as a link when it has an href', () => {
    render(
      <StepBar
        label="Setup steps"
        steps={[{ label: 'One', href: '?step=0' }, { label: 'Two', href: '?step=1' }, { label: 'Three', href: '?step=2' }]}
        current={2}
      />,
    );
    expect(screen.getByRole('link', { name: /Step 1, done/ })).toHaveAttribute('href', '?step=0');
    expect(screen.getByRole('link', { name: /Step 2, done/ })).toHaveAttribute('href', '?step=1');
    expect(screen.queryByRole('link', { name: /Three/ })).toBeNull();
  });

  it('hides the number from assistive technology (the name carries it)', () => {
    render(<StepBar label="Setup steps" steps={STEPS} current={0} />);
    const num = screen.getByText('1');
    expect(num).toHaveAttribute('aria-hidden', 'true');
  });

  it('clamps a current step past either end', () => {
    const { rerender } = render(<StepBar label="Setup steps" steps={STEPS} current={9} />);
    expect(document.querySelector('[aria-current="step"]')).toHaveTextContent('Check');
    rerender(<StepBar label="Setup steps" steps={STEPS} current={-3} />);
    expect(document.querySelector('[aria-current="step"]')).toHaveTextContent('The service');
  });

  it('has no axe violations', async () => {
    const { container } = render(<StepBar label="Setup steps" steps={STEPS} current={2} onSelect={() => undefined} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
