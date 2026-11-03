import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { AttentionRail, PlanningStage, type PlanningStageName } from './PlanningStage';

const counts = { accepting: 4, limited: 2, 'not-accepting': 1, 'over-capacity': 1, 'not-updated': 1 };

function stage(name: PlanningStageName) {
  return render(
    <PlanningStage
      stage={name}
      counts={counts}
      listWide={<p>wide list</p>}
      rail={<p>rail list</p>}
      service={<h2>service stage</h2>}
      sideHome={<p>home side</p>}
      sideService={<p>service side</p>}
      sideAlert={<button type="button">Acknowledge</button>}
    />,
  );
}

const layerOf = (text: string) => screen.getByText(text, { selector: 'p, h2, button' }).closest('[data-layer]') as HTMLElement;

describe('PlanningStage', () => {
  it('names its stage, home, service or alert, on the grid', () => {
    const { container, rerender } = stage('home');
    expect(container.querySelector('[data-planning-stage]')).toHaveAttribute('data-planning-stage', 'home');
    for (const name of ['service', 'alert'] as const) {
      rerender(<PlanningStage stage={name} counts={counts} />);
      expect(container.querySelector('[data-planning-stage]')).toHaveAttribute('data-planning-stage', name);
    }
  });

  it('shows five status tiles with a number and a word each, large at home and folded to a strip after', () => {
    const { rerender } = stage('home');
    const group = screen.getByRole('group', { name: 'Services by state' });
    const tiles = within(group).getAllByRole('listitem');
    expect(tiles.map((tile) => tile.textContent?.replace(/[^\w ]/g, '').trim())).toEqual([
      '4 Accepting',
      '2 Limited',
      '1 Not accepting',
      '1 Over capacity',
      '1 Not updated',
    ]);
    expect(group).toHaveAttribute('data-compact', 'false');
    rerender(<PlanningStage stage="service" counts={counts} />);
    expect(screen.getByRole('group', { name: 'Services by state' })).toHaveAttribute('data-compact', 'true');
  });

  it('shows the wide list and the home side at home, and hides the rail, the service and the other sides', () => {
    stage('home');
    expect(layerOf('wide list')).toHaveAttribute('data-layer', 'current');
    expect(layerOf('home side')).toHaveAttribute('data-layer', 'current');
    for (const text of ['rail list', 'service stage', 'service side', 'Acknowledge']) {
      const layer = layerOf(text);
      expect(layer).not.toHaveAttribute('data-layer', 'current');
      expect(layer).toHaveAttribute('inert');
      expect(layer).toHaveAttribute('aria-hidden', 'true');
    }
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
  });

  it('opens a service in place: the list becomes a rail, the service takes the stage, its alert waits beside it', () => {
    stage('service');
    expect(layerOf('rail list')).toHaveAttribute('data-layer', 'current');
    expect(layerOf('service stage')).toHaveAttribute('data-layer', 'current');
    expect(layerOf('service side')).toHaveAttribute('data-layer', 'current');
    expect(layerOf('wide list')).toHaveAttribute('inert');
    expect(layerOf('home side')).toHaveAttribute('inert');
    expect(layerOf('Acknowledge')).toHaveAttribute('inert');
  });

  it('opens the alert beside the service, which stays on the stage, with Acknowledge reachable', () => {
    stage('alert');
    expect(layerOf('service stage')).toHaveAttribute('data-layer', 'current');
    expect(layerOf('rail list')).toHaveAttribute('data-layer', 'current');
    expect(layerOf('Acknowledge')).toHaveAttribute('data-layer', 'current');
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeInTheDocument();
    expect(layerOf('service side')).toHaveAttribute('inert');
  });

  it('keeps the side column in the same place at every stage, so the actions do not move', () => {
    const { container, rerender } = stage('service');
    const side = () => container.querySelector('[data-area="side"]');
    const first = side();
    rerender(
      <PlanningStage stage="alert" counts={counts} sideService={<p>service side</p>} sideAlert={<button type="button">Acknowledge</button>} />,
    );
    expect(side()).toBe(first);
    expect(side()?.parentElement).toHaveAttribute('data-stage', '2');
  });

  it('has no accessibility violations at home', async () => {
    const { container } = stage('home');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('AttentionRail', () => {
  const entries = [
    { serviceId: 'a', name: 'Hospital at home', status: 'over-capacity' },
    { serviceId: 'b', name: 'SDEC · Site 2', status: 'not-accepting' },
    { serviceId: 'c', name: 'Virtual ward · frailty', status: 'not-updated' },
  ];

  it('lists each service that needs attention, with its status in words, as a link to the service', () => {
    render(<AttentionRail entries={entries} />);
    const list = screen.getByRole('list', { name: 'Needs attention, in brief' });
    expect(within(list).getAllByRole('link')).toHaveLength(3);
    expect(within(list).getByRole('link', { name: /Hospital at home/ })).toHaveAttribute('href', '/planning/services/a');
    expect(within(list).getByText('Over capacity')).toBeInTheDocument();
    expect(within(list).getByText('Not accepting')).toBeInTheDocument();
    expect(within(list).getByText('Not updated')).toBeInTheDocument();
  });

  it('marks the service that is open', () => {
    render(<AttentionRail entries={entries} currentId="b" />);
    expect(screen.getByRole('link', { name: /SDEC/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Hospital at home/ })).not.toHaveAttribute('aria-current');
  });
});
