import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReporterStage, type ReporterStageState } from './ReporterStage';

// The one page the three routes become: the list never goes away, and the stage area holds the compose
// panel or the detail by state (browse, compose, detail, number; number is the detail with its number row open).

function show(state: ReporterStageState) {
  return render(
    <ReporterStage
      state={state}
      list={<button type="button">The list</button>}
      compose={<p>Compose panel</p>}
      detail={<p>Detail panel</p>}
    />,
  );
}

function grid(container: HTMLElement): HTMLElement {
  return container.querySelector('[data-stage]') as HTMLElement;
}

describe('ReporterStage', () => {
  it('browse: the list takes the width and the stage panels are out of reach', () => {
    const { container } = show('browse');
    expect(grid(container).style.gridTemplateColumns).toBe('minmax(0,1fr) 0px 0px');
    expect(screen.getByRole('button', { name: 'The list' })).toBeInTheDocument();
    expect(screen.getByText('Compose panel').closest('[data-layer]')).toHaveAttribute('inert');
    expect(screen.getByText('Detail panel').closest('[data-layer]')).toHaveAttribute('inert');
  });

  it('compose: the list is 420px and the compose panel is the stage', () => {
    const { container } = show('compose');
    expect(grid(container).style.gridTemplateColumns).toBe('420px minmax(0,1fr) 0px');
    expect(screen.getByText('Compose panel').closest('[data-layer]')).not.toHaveAttribute('inert');
    expect(screen.getByText('Detail panel').closest('[data-layer]')).toHaveAttribute('inert');
    expect(screen.getByRole('button', { name: 'The list' })).toBeInTheDocument();
  });

  it('detail: the list is 340px and the detail is the stage', () => {
    const { container } = show('detail');
    expect(grid(container).style.gridTemplateColumns).toBe('340px minmax(0,1fr) 0px');
    expect(screen.getByText('Detail panel').closest('[data-layer]')).not.toHaveAttribute('inert');
    expect(screen.getByText('Compose panel').closest('[data-layer]')).toHaveAttribute('inert');
  });

  it('number: the same columns as detail, and the detail stays the stage', () => {
    const { container } = show('number');
    expect(grid(container).style.gridTemplateColumns).toBe('340px minmax(0,1fr) 0px');
    expect(screen.getByText('Detail panel').closest('[data-layer]')).not.toHaveAttribute('inert');
  });

  it('numbers the stages browse 0, compose 1, detail 2 and number 3', () => {
    const stages = (['browse', 'compose', 'detail', 'number'] as const).map((state) => {
      const { container, unmount } = show(state);
      const value = grid(container).getAttribute('data-stage');
      unmount();
      return value;
    });
    expect(stages).toEqual(['0', '1', '2', '3']);
  });

  it('keeps the list in the page in every state', () => {
    for (const state of ['browse', 'compose', 'detail', 'number'] as const) {
      const { unmount } = show(state);
      expect(screen.getByRole('button', { name: 'The list' })).toBeInTheDocument();
      unmount();
    }
  });
});
