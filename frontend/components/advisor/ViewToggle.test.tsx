import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import { ViewToggle } from './ViewToggle';

beforeEach(() => push.mockReset());

describe('ViewToggle (W50)', () => {
  it('marks the current view pressed, and the other one not', () => {
    render(<ViewToggle caseId="4821" current="list" />);

    expect(byEl('ADV-MAP-TOGGLE-LIST')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('ADV-MAP-TOGGLE-MAP')).toHaveAttribute('aria-pressed', 'false');
  });

  it('Map goes to the map, and List goes back to the options list', async () => {
    const user = userEvent.setup();
    render(<ViewToggle caseId="4821" current="list" />);
    await user.click(byEl('ADV-MAP-TOGGLE-MAP'));
    expect(push).toHaveBeenLastCalledWith('/advisor/case/4821/map');

    render(<ViewToggle caseId="4821" current="map" />);
    await user.click(screen.getAllByRole('button', { name: 'List' }).at(-1) as HTMLElement);
    expect(push).toHaveBeenLastCalledWith('/advisor/case/4821/options');
  });

  it('has no axe violations', async () => {
    const { container } = render(<ViewToggle caseId="4821" current="map" />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
