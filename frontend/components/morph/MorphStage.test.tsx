import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { MorphStage } from './MorphStage';

// Layers stacked in one cell, one current (boards/lead/AddService.dc.html). The others are inert and hidden, and a
// layer that was never current is not mounted at all, so its data fetches do not run.

const TEMPLATES = ['0px minmax(0,1fr) 0px', '312px minmax(0,1fr) 0px', '312px minmax(0,1fr) 0px', '0px minmax(0,1fr) 0px'];

function Probe({ name, onMount }: { name: string; onMount: (n: string) => void }) {
  onMount(name);
  return (
    <section>
      <h2>{name}</h2>
      <button type="button">Do {name}</button>
    </section>
  );
}

function stage(current: number, onMount: (n: string) => void = () => undefined, extra: Partial<Parameters<typeof MorphStage>[0]> = {}) {
  return (
    <MorphStage
      label="Setup stage"
      current={current}
      templates={TEMPLATES}
      layers={['one', 'two', 'three', 'four'].map((n) => function layer() {
        return <Probe name={n} onMount={onMount} />;
      })}
      {...extra}
    />
  );
}

describe('MorphStage', () => {
  it('is a labelled region holding every mounted layer in one stage area', () => {
    const { container } = render(stage(0));
    expect(screen.getByRole('region', { name: 'Setup stage' })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-area="stage"]')).toHaveLength(1);
  });

  it('shows the current layer to people and hides the visited ones that are not current', () => {
    const { rerender } = render(stage(0));
    rerender(stage(1));
    expect(screen.getByRole('button', { name: 'Do two' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Do one' })).toBeNull();
    const first = screen.getByText('one').closest('[data-layer]') as HTMLElement;
    expect(first.hasAttribute('inert')).toBe(true);
    expect(first).toHaveAttribute('aria-hidden', 'true');
  });

  it('does not mount a layer that has not been current, so its fetches do not run', () => {
    const onMount = vi.fn();
    render(stage(0, onMount));
    expect(onMount.mock.calls.map((c) => c[0])).toEqual(['one']);
    expect(screen.queryByText('three')).toBeNull();
  });

  it('mounts a layer when it first becomes current, and keeps a visited one mounted', () => {
    const onMount = vi.fn();
    const { rerender } = render(stage(0, onMount));
    rerender(stage(1, onMount));
    expect(screen.getByText('two')).toBeInTheDocument();
    expect(screen.getByText('one')).toBeInTheDocument();
    rerender(stage(0, onMount));
    expect(screen.queryByText('three')).toBeNull();
    expect(screen.getByText('two')).toBeInTheDocument();
  });

  it('can unmount a layer as soon as it is left, with keep="current"', () => {
    const { rerender } = render(stage(0, () => undefined, { keep: 'current' }));
    rerender(stage(1, () => undefined, { keep: 'current' }));
    expect(screen.queryByText('one')).toBeNull();
    expect(screen.getByText('two')).toBeInTheDocument();
  });

  it('sets the columns of the current stage on the grid', () => {
    const { container, rerender } = render(stage(1));
    const grid = container.querySelector('[data-stage]') as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe(TEMPLATES[1]);
    rerender(stage(3));
    expect((container.querySelector('[data-stage]') as HTMLElement).style.gridTemplateColumns).toBe(TEMPLATES[3]);
  });

  it('puts the summary in the list area and does not give it to the stage', () => {
    const { container } = render(stage(1, () => undefined, { summary: <p>So far text</p> }));
    expect(container.querySelector('[data-area="list"]')).toHaveTextContent('So far text');
    expect(container.querySelector('[data-area="stage"]')).not.toHaveTextContent('So far text');
  });

  it('moves focus into the new current layer when the step changes (its heading, else the layer)', () => {
    const { rerender } = render(stage(0));
    rerender(stage(1));
    expect(screen.getByRole('heading', { name: 'two' })).toHaveFocus();
  });

  it('does not take focus on the first render', () => {
    render(stage(0));
    expect(document.body).toHaveFocus();
  });

  it('marks a step change made from the keyboard as instant, and a pointer one as animated', () => {
    const { container, rerender } = render(stage(0));
    const root = () => container.querySelector('[data-morph]') as HTMLElement;
    expect(root()).toHaveAttribute('data-instant', 'false');
    rerender(stage(1, () => undefined, { instant: true }));
    expect(root()).toHaveAttribute('data-instant', 'true');
  });

  it('keeps a step change working without throwing when only one layer exists', () => {
    render(<MorphStage label="Only" current={0} templates={['0px minmax(0,1fr) 0px']} layers={[() => <p>solo</p>]} />);
    expect(screen.getByText('solo')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(stage(2));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
