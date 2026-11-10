import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import { ViewToggle } from './ViewToggle';

beforeEach(() => push.mockReset());

const TABS = [
  ['List', '/advisor/case/4821/options'],
  ['Compare', '/advisor/case/4821/compare'],
  ['Map', '/advisor/case/4821/map'],
  ['Ways', '/advisor/case/4821/ways'],
  ['Other organisations', '/advisor/case/4821/network-options'],
] as const;

describe('ViewToggle: the one segmented control over the options (W50)', () => {
  it('has List, Compare, Map, Ways and Other organisations, in that order, as links to the existing routes', () => {
    render(<ViewToggle caseId="4821" current="list" />);

    const nav = screen.getByRole('navigation', { name: 'Options view' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual(TABS.map(([name, href]) => [name, href]));
  });

  it('marks only the current view aria-current page', () => {
    for (const [current, name] of [
      ['list', 'List'],
      ['compare', 'Compare'],
      ['map', 'Map'],
      ['ways', 'Ways'],
    ] as const) {
      const { unmount } = render(<ViewToggle caseId="4821" current={current} />);
      const marked = document.querySelectorAll('[aria-current="page"]');
      expect(marked).toHaveLength(1);
      expect(marked[0]).toHaveTextContent(name);
      unmount();
    }
  });

  it('keeps the data-el ids of the List and Map tabs', () => {
    render(<ViewToggle caseId="4821" current="map" />);

    expect(byEl('ADV-MAP-TOGGLE-MAP')).toHaveAttribute('aria-current', 'page');
    expect(byEl('ADV-MAP-TOGGLE-LIST')).not.toHaveAttribute('aria-current');
  });

  it('encodes the case id in every link', () => {
    render(<ViewToggle caseId="a b/1" current="list" />);

    for (const link of within(screen.getByRole('navigation', { name: 'Options view' })).getAllByRole('link')) {
      expect(link.getAttribute('href')).toMatch(/^\/advisor\/case\/a%20b%2F1\//);
    }
  });

  it('has no axe violations', async () => {
    const { container } = render(<ViewToggle caseId="4821" current="map" />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('ViewToggle: the network variant (WB11)', () => {
  it('marks Other organisations as the current view', () => {
    render(<ViewToggle caseId="4821" current="list" scope="network" />);

    const marked = document.querySelectorAll('[aria-current="page"]');
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveTextContent('Other organisations');
  });

  it('goes between the network map and the network list of the same case, with the same ids', async () => {
    const user = userEvent.setup();
    render(<ViewToggle caseId="4821" current="list" scope="network" />);
    expect(byEl('ADV-MAP-TOGGLE-LIST')).toHaveAttribute('aria-pressed', 'true');
    await user.click(byEl('ADV-MAP-TOGGLE-MAP'));
    expect(push).toHaveBeenLastCalledWith('/advisor/case/4821/network-map');
    render(<ViewToggle caseId="4821" current="map" scope="network" />);
    await user.click(screen.getAllByRole('button', { name: 'List' }).at(-1) as HTMLElement);
    expect(push).toHaveBeenLastCalledWith('/advisor/case/4821/network-options');
  });

  it('choosing the view already shown does nothing', async () => {
    const user = userEvent.setup();
    render(<ViewToggle caseId="4821" current="list" scope="network" />);
    await user.click(byEl('ADV-MAP-TOGGLE-LIST'));
    expect(push).not.toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ViewToggle caseId="4821" current="map" scope="network" />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
