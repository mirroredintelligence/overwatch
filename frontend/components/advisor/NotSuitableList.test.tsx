import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OPTIONS_VIEW } from '@/test/fixtures/options';
import { NotSuitableList } from './NotSuitableList';

describe('NotSuitableList (W13)', () => {
  it('is a disclosure that says how many services are not suitable and why', async () => {
    const user = userEvent.setup();
    render(<NotSuitableList items={OPTIONS_VIEW.notSuitable} />);
    const toggle = screen.getByRole('button', { name: '3 services not suitable, and why' });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('SDEC · Site 2: not accepting since 13:30')).toBeNull();

    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('SDEC · Site 2: not accepting since 13:30')).toBeInTheDocument();
    expect(screen.getByText('Virtual ward · frailty: not updated since 09:02')).toBeInTheDocument();
    expect(screen.getByText('Reablement: outside the criteria for this district')).toBeInTheDocument();
  });

  it('says one service in the singular', () => {
    render(<NotSuitableList items={[OPTIONS_VIEW.notSuitable[0]]} />);
    expect(screen.getByRole('button', { name: '1 service not suitable, and why' })).toBeInTheDocument();
  });

  it('has no axe violations when open', async () => {
    const user = userEvent.setup();
    const { container } = render(<NotSuitableList items={OPTIONS_VIEW.notSuitable} />);
    await user.click(screen.getByRole('button', { name: '3 services not suitable, and why' }));
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
