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

  it('marks the disclosure chevron as decorative, so the words carry the open and closed state', () => {
    const { container } = render(<NotSuitableList items={OPTIONS_VIEW.notSuitable} />);
    const chevron = container.querySelector('button svg');

    expect(chevron).not.toBeNull();
    expect(chevron).toHaveAttribute('aria-hidden', 'true');
  });

  it('has no axe violations when open', async () => {
    const user = userEvent.setup();
    const { container } = render(<NotSuitableList items={OPTIONS_VIEW.notSuitable} />);
    await user.click(screen.getByRole('button', { name: '3 services not suitable, and why' }));
    expect((await runAxe(container)).violations).toEqual([]);
  });
});


describe('NotSuitableList: a network’s rows (WB11)', () => {
  it('names the organisation of each row, with the service and the reason', async () => {
    const user = userEvent.setup();
    render(
      <NotSuitableList
        items={[
          { serviceId: 'lst-1', name: 'Care packages north', reason: 'not accepting', organisation: 'Sample Area B' },
          { serviceId: 'lst-2', name: 'UCR East', reason: 'outside criteria' },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: '2 services not suitable, and why' }));
    expect(screen.getByText('Care packages north (Sample Area B): not accepting')).toBeInTheDocument();
    expect(screen.getByText('UCR East: outside criteria')).toBeInTheDocument();
  });
});
