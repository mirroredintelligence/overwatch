import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CallStage, type CallStageName } from './CallStage';

const COLUMNS: Record<CallStageName, string> = {
  overview: '0px minmax(0,1fr) 340px',
  needs: '0px minmax(0,1fr) 320px',
  options: '300px minmax(0,1fr) 0px',
  request: '270px minmax(0,1fr) 300px',
};

function stage(step: CallStageName) {
  return (
    <CallStage step={step} summary={<p>The patient card</p>} side={<p>Alongside content</p>}>
      <h2>Stage heading</h2>
      <button type="button">A stage action</button>
    </CallStage>
  );
}

const grid = (container: HTMLElement) => container.querySelector('[data-stage]') as HTMLElement;
const column = (name: 'list' | 'stage' | 'side') => document.querySelector(`[data-area="${name}"]`) as HTMLElement;

describe('CallStage: the grid of a call (Call board, four stages)', () => {
  it.each([
    ['overview', '0'],
    ['needs', '1'],
    ['options', '2'],
    ['request', '3'],
  ] as const)('%s is stage %s of the grid, with its own columns', (step, index) => {
    const { container } = render(stage(step));

    expect(grid(container)).toHaveAttribute('data-stage', index);
    expect(grid(container).style.gridTemplateColumns).toBe(COLUMNS[step]);
  });

  it('puts the summary, the stage and the side in their areas', () => {
    render(stage('request'));

    expect(column('list')).toHaveTextContent('The patient card');
    expect(column('stage')).toHaveTextContent('Stage heading');
    expect(column('side')).toHaveTextContent('Alongside content');
  });

  it('folds the summary away (inert, hidden from readers) before the options, and shows it from the options on', () => {
    const card = () => screen.getByText('The patient card');
    const { rerender } = render(stage('overview'));
    expect(card().closest('[inert]')).not.toBeNull();
    expect(card().closest('[aria-hidden="true"]')).not.toBeNull();

    rerender(stage('needs'));
    expect(card().closest('[inert]')).not.toBeNull();

    rerender(stage('options'));
    expect(card().closest('[inert]')).toBeNull();
    expect(card().closest('[aria-hidden="true"]')).toBeNull();

    rerender(stage('request'));
    expect(column('list').querySelector('[inert]')).toBeNull();
  });

  it('folds the side away on the options and shows it on the other three stages', () => {
    const { rerender } = render(stage('options'));
    expect(column('side').querySelector('[inert]')).not.toBeNull();
    expect(screen.queryByRole('complementary', { name: 'Alongside' })).toBeNull();

    for (const step of ['overview', 'needs', 'request'] as const) {
      rerender(stage(step));
      expect(column('side').querySelector('[inert]')).toBeNull();
      expect(screen.getByRole('complementary', { name: 'Alongside' })).toHaveTextContent('Alongside content');
    }
  });

  it('keeps the stage itself reachable at every stage', () => {
    for (const step of ['overview', 'needs', 'options', 'request'] as const) {
      const { unmount } = render(stage(step));
      expect(screen.getByRole('button', { name: 'A stage action' })).toBeInTheDocument();
      unmount();
    }
  });

  it('does not take focus on first render', () => {
    render(stage('needs'));

    expect(document.body).toHaveFocus();
  });

  it('moves focus to the stage heading when the person moves to another stage', () => {
    const { rerender } = render(stage('needs'));

    rerender(stage('options'));

    const heading = screen.getByRole('heading', { name: 'Stage heading' });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute('tabindex', '-1');
  });

  it('does not move focus when it re-renders on the same stage', () => {
    const { rerender } = render(stage('needs'));
    screen.getByRole('button', { name: 'A stage action' }).focus();

    rerender(stage('needs'));

    expect(screen.getByRole('button', { name: 'A stage action' })).toHaveFocus();
  });

  it('works without a summary or a side', () => {
    const { container } = render(
      <CallStage step="options">
        <h2>Alone</h2>
      </CallStage>,
    );

    expect(screen.getByRole('heading', { name: 'Alone' })).toBeInTheDocument();
    expect(grid(container)).toHaveAttribute('data-stage', '2');
  });

  it('has no axe violations', async () => {
    const { container } = render(<main>{stage('request')}</main>);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
